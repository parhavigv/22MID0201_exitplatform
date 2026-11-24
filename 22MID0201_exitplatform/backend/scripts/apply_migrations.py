"""
Apply the SQL in supabase/migrations/ to the database in DATABASE_URL.

Tracks what has run in a `schema_migrations` table, so re-running is safe:
already-applied files are skipped. Each file runs inside its own transaction —
a failure rolls that file back and stops, leaving the database consistent.

    python scripts/apply_migrations.py            # migrations only
    python scripts/apply_migrations.py --seed     # then run seed.sql
    python scripts/apply_migrations.py --status   # show what's applied

Seed is never applied automatically: seed.sql creates demo auth users, which
must not land in a production database by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import unquote

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
SEED_FILE = ROOT / "supabase" / "seed.sql"

# The tracking table lives in `public`, so PostgREST would happily serve it to
# any signed-in user. RLS on with zero policies denies everyone; the service
# role, which this script uses, bypasses RLS and is unaffected.
TRACKING_TABLE = """
create table if not exists schema_migrations (
    filename    text primary key,
    checksum    text not null,
    applied_at  timestamptz not null default now()
);
alter table schema_migrations enable row level security;
revoke all on schema_migrations from anon, authenticated;
"""


def split_dsn(url: str) -> tuple[str, int, str, str, str]:
    """Split a postgres URI into (host, port, user, password, dbname).

    Hand-rolled rather than urlsplit: the password may legally contain @ : / and
    brackets, which urlsplit either mis-parses or rejects outright. Splitting on
    the LAST '@' and the LAST ':' of the host part is unambiguous even then.
    """
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            rest = url[len(scheme) :]
            break
    else:
        raise ValueError("must start with postgresql:// or postgres://")

    if "@" not in rest:
        raise ValueError("no credentials found before '@'")
    credentials, _, host_part = rest.rpartition("@")

    if ":" not in credentials:
        raise ValueError("no ':' between username and password")
    user, _, password = credentials.partition(":")

    host_port, _, dbname = host_part.partition("/")
    dbname = dbname.split("?")[0] or "postgres"

    if ":" not in host_port:
        raise ValueError("no port in the host section")
    host, _, port_text = host_port.rpartition(":")
    if not port_text.isdigit():
        raise ValueError(f"port is not a number: {port_text!r}")

    return host, int(port_text), unquote(user), unquote(password), dbname


def connect() -> psycopg.Connection:
    load_dotenv(ROOT / "backend" / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or url == "PASTE_HERE":
        sys.exit(
            "DATABASE_URL is not set.\n\n"
            "Supabase dashboard -> Connect -> Direct -> Session pooler -> URI. "
            "Replace [YOUR-PASSWORD] with your database password, then put the "
            "whole string in backend/.env as DATABASE_URL=..."
        )

    if "[YOUR-PASSWORD]" in url:
        sys.exit(
            "DATABASE_URL still has the [YOUR-PASSWORD] placeholder in it.\n\n"
            "Replace it — square brackets included — with your database password.\n"
            "Supabase -> Settings -> Database -> Reset database password."
        )

    try:
        host, port, user, password, dbname = split_dsn(url)
    except ValueError as exc:
        sys.exit(f"DATABASE_URL could not be parsed: {exc}")

    try:
        # Components as keywords, never the raw URI. Supabase-generated
        # passwords routinely contain @ : / [ ] % — any of which would derail a
        # URI parser and surface as a misleading "authentication failed".
        return psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            sslmode="require",
            connect_timeout=15,
            autocommit=False,
        )
    except psycopg.OperationalError as exc:
        message = str(exc)
        hint = ""
        if "password authentication failed" in message:
            hint = (
                "\nThe host and username are reachable, so this is the password.\n"
                "Reset it: Supabase -> Settings -> Database -> Reset database "
                "password -> Generate. Then update DATABASE_URL in backend/.env."
            )
        elif "timeout" in message.lower() or "could not translate" in message:
            hint = (
                "\nCould not reach the host. Make sure you copied the SESSION "
                "POOLER string (host contains 'pooler.supabase.com'), not the "
                "direct connection, which is IPv6-only."
            )
        sys.exit(f"Could not connect to the database.\n\n{message}{hint}")


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def applied(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(TRACKING_TABLE)
        conn.commit()
        cur.execute("select filename, checksum from schema_migrations")
        return dict(cur.fetchall())


def run_file(conn: psycopg.Connection, path: Path, record: bool) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        try:
            cur.execute(sql)  # type: ignore[arg-type]
            if record:
                cur.execute(
                    "insert into schema_migrations (filename, checksum) values (%s, %s)",
                    (path.name, checksum(sql)),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="run seed.sql afterwards")
    parser.add_argument("--status", action="store_true", help="list applied migrations")
    args = parser.parse_args()

    conn = connect()
    done = applied(conn)

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        sys.exit(f"No migrations found in {MIGRATIONS_DIR}")

    if args.status:
        for path in files:
            current = checksum(path.read_text(encoding="utf-8"))
            if path.name not in done:
                mark, note = "PENDING", ""
            elif done[path.name] != current:
                mark, note = "CHANGED", "  <- edited since it was applied"
            else:
                mark, note = "applied", ""
            print(f"  [{mark:>7}] {path.name}{note}")
        return 0

    pending = 0
    for path in files:
        sql = path.read_text(encoding="utf-8")
        if path.name in done:
            if done[path.name] != checksum(sql):
                print(
                    f"  ! {path.name} has changed since it was applied. "
                    "Migrations are immutable — add a new file instead."
                )
            else:
                print(f"  - {path.name} (already applied)")
            continue

        print(f"  > {path.name} ... ", end="", flush=True)
        try:
            run_file(conn, path, record=True)
        except Exception as exc:
            print("FAILED")
            print(f"\n{exc}")
            return 1
        print("ok")
        pending += 1

    print(f"\n{pending} migration(s) applied." if pending else "\nNothing to apply.")

    if args.seed:
        print(f"\n  > {SEED_FILE.name} ... ", end="", flush=True)
        try:
            run_file(conn, SEED_FILE, record=False)
        except Exception as exc:
            print("FAILED")
            print(f"\n{exc}")
            return 1
        print("ok")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
