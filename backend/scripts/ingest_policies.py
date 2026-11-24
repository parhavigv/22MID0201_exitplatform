"""Ingest sample HR exit policy documents into Supabase policy_chunks.

Reads every .md file under backend/data/policies/, extracts the title and
version from the front-matter (lines starting with # and **Version:**), then
runs the full chunk → embed → upsert pipeline via app.services.rag.

Prerequisites
-------------
1. Migration 0005_policy_rag.sql applied:
       python scripts/apply_migrations.py
2. openai package installed:
       pip install openai>=1.54.0
3. Supabase running and SUPABASE_SERVICE_KEY + PORTKEY_* set in backend/.env

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/ingest_policies.py

    # Re-ingest a single file (idempotent — replaces existing chunks):
    .venv/Scripts/python.exe scripts/ingest_policies.py --file data/policies/01_notice_period_policy.md

Re-running is always safe — the ingest function deletes old chunks before
inserting new ones when the (title, version) already exists in policy_docs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.services.rag import ingest_policy_doc  # noqa: E402


POLICIES_DIR = ROOT / "data" / "policies"


def _uploader_id() -> str:
    """The HR employee recorded as having uploaded these policies.

    Looked up rather than hardcoded: policy_docs.uploaded_by is a foreign key
    into employees, and a literal UUID here silently rots the moment the seed
    is regenerated with fresh ids.
    """
    from app.deps import service_db  # noqa: PLC0415

    result = (
        service_db()
        .table("employees")
        .select("id")
        .eq("app_role", "hr")
        .eq("is_active", True)
        .order("emp_code")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise SystemExit(
            "No active HR employee found — run scripts/apply_migrations.py --seed first."
        )
    return result.data[0]["id"]


def _parse_title_version(text: str) -> tuple[str, str]:
    """Extract title from the first # heading and version from **Version:** line."""
    title = "Unknown Policy"
    version = "1.0"

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# ") and title == "Unknown Policy":
            title = line.lstrip("# ").strip()
        match = re.search(r"\*\*Version:\*\*\s*([^\s*]+)", line)
        if match:
            version = match.group(1)

    return title, version


def ingest_file(path: Path, uploader_id: str) -> None:
    content = path.read_text(encoding="utf-8")
    title, version = _parse_title_version(content)
    print(f"\n-> {path.name}")
    print(f"  Title:   {title}")
    print(f"  Version: {version}")

    result = ingest_policy_doc(
        title=title,
        version=version,
        content=content,
        uploaded_by=uploader_id,
    )
    print(f"  Chunks ingested: {result['chunks_ingested']}")
    print(f"  Approx tokens:  {result['tokens_approx']}")
    print(f"  doc_id:         {result['doc_id']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest policy docs into Supabase")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Ingest a single file instead of the whole policies directory.",
    )
    args = parser.parse_args()

    if not os.environ.get("SUPABASE_URL"):
        print("ERROR: SUPABASE_URL not set in backend/.env")
        return 1
    if not os.environ.get("PORTKEY_API_KEY"):
        print("ERROR: PORTKEY_API_KEY not set in backend/.env")
        return 1

    if args.file:
        files = [args.file]
    else:
        if not POLICIES_DIR.is_dir():
            print(f"ERROR: policies directory not found at {POLICIES_DIR}")
            return 1
        files = sorted(POLICIES_DIR.glob("*.md"))
        if not files:
            print(f"No .md files found in {POLICIES_DIR}")
            return 1

    print(f"Ingesting {len(files)} file(s) from {POLICIES_DIR}")
    print("=" * 60)

    uploader_id = _uploader_id()

    errors = 0
    for path in files:
        try:
            ingest_file(path, uploader_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            errors += 1

    print("\n" + "=" * 60)
    if errors:
        print(f"Done with {errors} error(s).")
        return 1
    print(f"Done. {len(files)} document(s) ingested successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
