"""Print the registered API routes. A quick check that every router loaded."""

import sys
from pathlib import Path

# Run from anywhere: put backend/ on the path so `app` imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

schema = app.openapi()
rows = [
    (method.upper(), path)
    for path, operations in schema["paths"].items()
    for method in operations
]

for method, path in sorted(rows, key=lambda r: (r[1], r[0])):
    print(f"  {method:7} {path}")

print(f"\n{len(rows)} routes")
