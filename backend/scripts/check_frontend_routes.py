"""Cross-check every endpoint the frontend calls against the backend's routes.

Why this exists
---------------
Two endpoints the UI depends on — `/cases/{id}/detail` and `/employees` — were
never implemented. Nothing failed at build time: `api.ts` just asked for a path
FastAPI had no route for, got a 404, and the page rendered its generic "not
available to you" state. It looked like a permissions bug and stayed hidden
until someone clicked that exact button.

This compares the two sides directly so the next such gap is found in a second
rather than in a demo.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/check_frontend_routes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

API_TS = ROOT.parent / "frontend" / "src" / "lib" / "api.ts"
OPENAPI = "http://127.0.0.1:8000/openapi.json"

# Any path parameter — `${caseId}` in a template literal, `{case_id}` in a
# FastAPI decorator — collapses to `{}` so the two sides compare as equals.
PARAM = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")


def normalise(path: str) -> str:
    return PARAM.sub("{}", path).split("?")[0].rstrip("/")


def backend_routes() -> set[tuple[str, str]]:
    """Read the routes off the running server's OpenAPI document.

    Importing app.main and walking `app.routes` looked simpler but reported
    every router as a single pathless entry, so it silently found nothing.
    The served spec is what the browser actually talks to, which makes it the
    honest thing to compare against.
    """
    try:
        spec = httpx.get(OPENAPI, timeout=15).json()
    except httpx.ConnectError:
        raise SystemExit(
            "Backend is not running on :8000 — start it, then re-run this check."
        )

    found = set()
    for path, operations in spec.get("paths", {}).items():
        if not path.startswith("/api"):
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                found.add((method.upper(), normalise(path[len("/api"):])))
    return found


def frontend_calls() -> set[tuple[str, str]]:
    source = API_TS.read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()

    def add(method: str, raw: str) -> None:
        # A path assembled entirely from variables tells us nothing about which
        # route it hits, so there is nothing to compare — skip rather than
        # report it as missing.
        path = normalise(raw)
        if path.startswith("/"):
            calls.add((method, path))

    # request<T>('/path', { method: 'PATCH' }) — method defaults to GET.
    for match in re.finditer(
        r"""request<[^>]*>\(\s*[`'"]([^`'"]+)[`'"]([^)]*)\)""", source, re.S
    ):
        method = re.search(r"method:\s*['\"](\w+)['\"]", match.group(2))
        add((method.group(1) if method else "GET"), match.group(1))

    # Raw fetch(`${BASE}/path`, { method }) — used where FormData is posted.
    for match in re.finditer(
        r"""fetch\(\s*`\$\{BASE\}([^`]+)`([^)]*)\)""", source, re.S
    ):
        method = re.search(r"method:\s*['\"](\w+)['\"]", match.group(2))
        add((method.group(1) if method else "GET"), match.group(1))

    return calls


def main() -> int:
    backend = backend_routes()
    calls = frontend_calls()
    missing = sorted(c for c in calls if c not in backend)

    print(f"frontend calls: {len(calls)}    backend routes: {len(backend)}\n")
    if not missing:
        print("OK - every endpoint the frontend calls exists on the backend.")
        return 0

    print(f"MISSING ({len(missing)}) - the frontend calls these, the backend has no route:")
    for method, path in missing:
        print(f"   {method:<7}/api{path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
