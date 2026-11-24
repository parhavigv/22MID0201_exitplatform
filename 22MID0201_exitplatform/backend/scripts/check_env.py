"""Report which environment variables are set, without printing secrets."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

KEYS = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_JWT_SECRET",
    "DATABASE_URL",
]

for key in KEYS:
    value = os.environ.get(key, "")
    if not value or value == "PASTE_HERE":
        print(f"{key:24} -- not set")
    elif key == "SUPABASE_URL":
        print(f"{key:24} {value}")
    elif key == "DATABASE_URL":
        # Mask the password; keep user, host and port visible for sanity checks.
        m = re.match(r"^(postgresql|postgres)://([^:]+):([^@]*)@([^:/]+):(\d+)/(\S+)$", value)
        if not m:
            print(f"{key:24} set, but not a recognisable postgres URI")
        else:
            scheme, user, password, host, port, db = m.groups()
            print(f"{key:24} {scheme}://{user}:***@{host}:{port}/{db}")
            print(f"{'  user':24} {user}")
            print(f"{'  password':24} {len(password)} chars")
    else:
        print(f"{key:24} set ({len(value)} chars)")
