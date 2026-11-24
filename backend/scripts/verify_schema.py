"""Structural check of what the migrations actually created."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.apply_migrations import connect  # noqa: E402

QUERIES = {
    "tables": """
        select tablename from pg_tables
        where schemaname = 'public' order by tablename
    """,
    "rls_disabled": """
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
        order by c.relname
    """,
    "policies": """
        select tablename, count(*) from pg_policies
        where schemaname = 'public' group by tablename order by tablename
    """,
    "helpers": """
        select p.proname from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'app' order by p.proname
    """,
    "extensions": """
        select extname from pg_extension
        where extname in ('vector','citext','pgcrypto') order by extname
    """,
}

COUNTS = [
    "exit_stages",
    "document_types",
    "task_templates",
    "employees",
    "exit_cases",
]


def main() -> int:
    conn = connect()
    cur = conn.cursor()

    cur.execute(QUERIES["tables"])
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables ({len(tables)}):")
    for i in range(0, len(tables), 3):
        print("   " + "".join(f"{t:<22}" for t in tables[i : i + 3]))

    cur.execute(QUERIES["extensions"])
    print(f"\nExtensions: {', '.join(r[0] for r in cur.fetchall())}")

    cur.execute(QUERIES["helpers"])
    print(f"RLS helpers in app schema: {', '.join(r[0] for r in cur.fetchall())}")

    cur.execute(QUERIES["rls_disabled"])
    unprotected = [r[0] for r in cur.fetchall()]
    if unprotected:
        print(f"\n!! RLS NOT ENABLED on: {', '.join(unprotected)}")
    else:
        print("\nRLS enabled on every public table.")

    cur.execute(QUERIES["policies"])
    policies = cur.fetchall()
    total = sum(c for _, c in policies)
    print(f"\nPolicies ({total} across {len(policies)} tables):")
    for name, count in policies:
        print(f"   {name:<22} {count}")

    # A table with RLS on and zero policies denies everything — usually a bug.
    with_policies = {name for name, _ in policies}
    silent = [t for t in tables if t not in with_policies and t != "schema_migrations"]
    if silent:
        print(f"\n!! RLS on but NO POLICIES (denies all reads): {', '.join(silent)}")

    print("\nSeeded rows:")
    for table in COUNTS:
        cur.execute(f"select count(*) from {table}")
        print(f"   {table:<22} {cur.fetchone()[0]}")

    cur.execute("select count(*) from auth.users")
    print(f"   {'auth.users':<22} {cur.fetchone()[0]}")

    cur.execute("""
        select count(*) from employees e
        left join auth.users u on u.id = e.auth_user_id
        where e.auth_user_id is null or u.id is null
    """)
    orphans = cur.fetchone()[0]
    print(f"\nEmployees without a working auth account: {orphans}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
