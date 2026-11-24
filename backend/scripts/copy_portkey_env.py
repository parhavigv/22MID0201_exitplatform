"""
Copy the Portkey gateway settings from the project-root .env into backend/.env.

Values are moved on disk and never printed. Existing keys in backend/.env are
replaced rather than duplicated, so this is safe to re-run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".env"
TARGET = ROOT / "backend" / ".env"

KEYS = ["PORTKEY_API_KEY", "PORTKEY_BASE_URL", "PORTKEY_MODEL"]


def read_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in KEYS:
            found[key.strip()] = value.strip().strip("\"'")
    return found


def main() -> int:
    values = read_values(SOURCE)
    missing = [k for k in KEYS if k not in values or not values[k]]
    if missing:
        print(f"Not found in {SOURCE}: {', '.join(missing)}")
        return 1

    if not TARGET.exists():
        print(f"No backend/.env at {TARGET}")
        return 1

    text = TARGET.read_text(encoding="utf-8")

    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"

    if "# --- LLM gateway" not in text:
        text = text.replace(
            "PORTKEY_API_KEY=",
            "# --- LLM gateway (Perficient self-hosted Portkey -> Vertex -> Claude) ---\n"
            "PORTKEY_API_KEY=",
            1,
        )

    TARGET.write_text(text, encoding="utf-8")

    for key in KEYS:
        shown = values[key] if key != "PORTKEY_API_KEY" else f"set ({len(values[key])} chars)"
        print(f"  {key:20} {shown}")
    print(f"\nWritten to backend/.env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
