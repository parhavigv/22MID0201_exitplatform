"""
Repair the commonest DATABASE_URL mistakes, without ever printing the password.

Fixes:
  * password still wrapped in the placeholder's [ ] brackets
  * surrounding quotes
  * stray whitespace

Run:  python scripts/fix_dsn.py          # report only
      python scripts/fix_dsn.py --write  # apply the fix
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.apply_migrations import split_dsn  # noqa: E402

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    write = "--write" in sys.argv

    if not ENV_PATH.exists():
        print(f"No .env at {ENV_PATH}")
        return 1

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    changed = False

    for i, line in enumerate(lines):
        if not line.startswith("DATABASE_URL="):
            continue

        url = line[len("DATABASE_URL=") :].strip().strip("\"'")
        try:
            host, port, user, password, dbname = split_dsn(url)
        except ValueError as exc:
            print(f"Cannot parse DATABASE_URL: {exc}")
            return 1

        print(f"  user      {user}")
        print(f"  host      {host}:{port}/{dbname}")
        print(f"  password  {len(password)} chars", end="")

        issues = []
        if password.startswith("[") and password.endswith("]"):
            issues.append("wrapped in [ ] — leftover placeholder brackets")
            password = password[1:-1]
        if password != password.strip():
            issues.append("has leading/trailing whitespace")
            password = password.strip()
        if (password.startswith('"') and password.endswith('"')) or (
            password.startswith("'") and password.endswith("'")
        ):
            issues.append("wrapped in quotes")
            password = password[1:-1]

        if not issues:
            print("  — looks clean")
            return 0

        print()
        for issue in issues:
            print(f"  PROBLEM   password {issue}")
        print(f"  FIXED     password would become {len(password)} chars")

        if write:
            lines[i] = f"DATABASE_URL=postgresql://{user}:{password}@{host}:{port}/{dbname}"
            changed = True
        else:
            print("\nRe-run with --write to apply.")
        break
    else:
        print("No DATABASE_URL line found in .env")
        return 1

    if changed:
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n.env updated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
