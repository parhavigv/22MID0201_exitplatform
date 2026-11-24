"""Manual sweep trigger — Phase 7.

Runs the nightly sweep immediately without waiting for APScheduler.
Use this to test the sweep locally or to force a sweep after seeding data.

Usage:
    cd backend
    .venv/Scripts/python.exe scripts/run_sweep.py                # all active cases
    .venv/Scripts/python.exe scripts/run_sweep.py <case_id>      # one specific case
"""

from __future__ import annotations

import sys
import os

# Ensure the backend package is importable when run from the scripts/ dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.jobs.sweep import sweep_all_active, sweep_case


def main() -> None:
    if len(sys.argv) > 1:
        case_id = sys.argv[1]
        print(f"\nRunning sweep for case {case_id[:8]}...\n")
        result = sweep_case(case_id)
        print(f"Status:   {result.status}")
        print(f"Drafted:  {result.actions_drafted} action(s)")
        if result.error:
            print(f"Error:    {result.error}")
    else:
        print("\nRunning sweep across all active cases...\n")
        results = sweep_all_active()

        ok = [r for r in results if r.status == "ok"]
        err = [r for r in results if r.status == "error"]
        total_drafted = sum(r.actions_drafted for r in results)

        print(f"\n{'─' * 50}")
        print(f"Cases swept:    {len(results)}")
        print(f"  OK:           {len(ok)}")
        print(f"  Errors:       {len(err)}")
        print(f"Actions drafted:{total_drafted}")

        if err:
            print("\nFailed cases:")
            for r in err:
                print(f"  {r.case_id[:8]}  {r.error}")

        if total_drafted > 0:
            print(
                "\nDrafted actions are in agent_actions with status='pending_approval'."
                "\nOpen the HR approval queue to review them."
            )


if __name__ == "__main__":
    main()
