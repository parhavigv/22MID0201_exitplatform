"""Create the LangGraph PostgresSaver checkpoint tables.

These tables (checkpoints, checkpoint_writes, checkpoint_blobs) are
LangGraph-owned — they don't belong in supabase/migrations/ alongside our
own schema, because they aren't our schema; LangGraph's own `.setup()`
creates and evolves them. `.setup()` uses CREATE TABLE IF NOT EXISTS
internally, so this is safe to re-run, same as apply_migrations.py.

    python scripts/setup_checkpointer.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import pg_connect_kwargs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    load_dotenv(ROOT / "backend" / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or url == "PASTE_HERE":
        print("DATABASE_URL is not set in backend/.env — see backend/.env.example.")
        return 1

    try:
        kwargs = pg_connect_kwargs(url)
    except ValueError as exc:
        print(f"DATABASE_URL could not be parsed: {exc}")
        return 1

    # Components as keywords, never the raw URI — see app/db.py docstring:
    # Supabase-generated passwords routinely contain characters that derail a
    # naive URI parser.
    with Connection.connect(**kwargs, autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
        saver = PostgresSaver(conn)
        saver.setup()

    print("Checkpoint tables ready (checkpoints, checkpoint_writes, checkpoint_blobs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
