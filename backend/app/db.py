"""Postgres connection helper for direct (non-PostgREST) access.

Only two callers need this: the LangGraph `PostgresSaver` checkpointer
(agent/graph.py) and its one-time setup script. Both need a psycopg
connection built from `DATABASE_URL` — the same thing
`scripts/apply_migrations.py` already does, and for the same reason:
Supabase-generated passwords routinely contain `@ : / [ ] %`, any of which
derails a naive URI parser into a misleading "authentication failed".

This mirrors that script's `split_dsn` rather than importing it —
`backend/scripts/` isn't meant to be imported from `backend/app/` (it's a
one-off CLI tools directory, not a package the app depends on). Keep the two
in sync by hand if DATABASE_URL's format assumptions ever change.
"""

from __future__ import annotations

from urllib.parse import unquote


def split_dsn(url: str) -> tuple[str, int, str, str, str]:
    """(host, port, user, password, dbname) from a postgres:// URI.

    Hand-rolled rather than urlsplit, which either mis-parses or rejects a
    password containing `@ : / [ ]` — split on the LAST '@' and LAST ':' of
    the host part instead, which stays unambiguous even then.
    """
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            rest = url[len(scheme) :]
            break
    else:
        raise ValueError("DATABASE_URL must start with postgresql:// or postgres://")

    if "@" not in rest:
        raise ValueError("DATABASE_URL: no credentials found before '@'")
    credentials, _, host_part = rest.rpartition("@")

    if ":" not in credentials:
        raise ValueError("DATABASE_URL: no ':' between username and password")
    user, _, password = credentials.partition(":")

    host_port, _, dbname = host_part.partition("/")
    dbname = dbname.split("?")[0] or "postgres"

    if ":" not in host_port:
        raise ValueError("DATABASE_URL: no port in the host section")
    host, _, port_text = host_port.rpartition(":")
    if not port_text.isdigit():
        raise ValueError(f"DATABASE_URL: port is not a number: {port_text!r}")

    return host, int(port_text), unquote(user), unquote(password), dbname


def pg_connect_kwargs(database_url: str) -> dict[str, object]:
    """Keyword connection args for `psycopg.Connection.connect(**kwargs)` —
    never the raw URI, for the reason in the module docstring."""
    host, port, user, password, dbname = split_dsn(database_url)
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "dbname": dbname,
        "sslmode": "require",
        "connect_timeout": 15,
    }
