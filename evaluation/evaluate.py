#!/usr/bin/env python3
"""Evaluation harness entry point.

Evaluates ONLY the requirement-change turn (QUANTITY_LIMIT 30 -> 60) of the
active Kiro session, by executionId. Produces one JSON and one HTML report under
evaluation/out/.

Two clearly separated halves:
  * Application checks   — independently rerun against a fresh backend process.
  * Kiro execution checks — derived from the recorded session log.

Read-only w.r.t. the session log and the repo (other than writing reports under
evaluation/out/). Does not modify Kiro settings, app code, tests, or unrelated
changes.

Usage:
    python3 evaluation/evaluate.py
    python3 evaluation/evaluate.py --skip-app-recheck   # session-log checks only
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make sibling modules importable whether run as a file or module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SESSIONS_DIR, TARGET_EXECUTION_ID, TARGET_PROMPT_PREFIX  # noqa: E402
from session_reader import find_current_session_log, load_turn  # noqa: E402
from kiro_checks import run_all_kiro_checks  # noqa: E402
from report import build_html, build_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the requirement-change turn.")
    ap.add_argument("--session-log", help="Explicit path to messages.jsonl (defaults to active session).")
    ap.add_argument("--skip-app-recheck", action="store_true",
                    help="Skip spawning a backend; run session-log checks only.")
    args = ap.parse_args()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)

    # 1) Locate + read the session log (read-only), isolate the target turn.
    session_log = args.session_log or find_current_session_log(SESSIONS_DIR)
    turn = load_turn(session_log, TARGET_EXECUTION_ID, TARGET_PROMPT_PREFIX)

    if not turn.tool_events and not turn.report_text:
        print(f"ERROR: no events found for executionId {TARGET_EXECUTION_ID} in\n  {session_log}",
              file=sys.stderr)
        return 2

    print(f"Selected turn executionId={turn.execution_id}")
    print(f"  session: {turn.session_id}")
    print(f"  window:  {turn.turn_start} -> {turn.turn_end}")
    print(f"  tool events: {len(turn.tool_events)}")

    # 2) Kiro execution checks (recorded).
    kiro_results = run_all_kiro_checks(turn)

    # 3) Application checks (independently rerun), unless skipped.
    if args.skip_app_recheck:
        from app_recheck import AppCheckResult
        from config import APP_CHECKS
        app_results = [AppCheckResult(lbl, "BLOCKED", "n/a", "n/a", "app re-check skipped")
                       for (lbl, *_rest) in APP_CHECKS]
        app_meta = {"host": None, "port": None, "started": False, "python": None,
                    "note": "skipped via --skip-app-recheck"}
    else:
        from app_recheck import run_app_checks
        print("Spawning fresh backend for independent application checks ...")
        app_results, app_meta = run_app_checks()
        print(f"  backend started={app_meta.get('started')} on port {app_meta.get('port')}")

    # 4) Render reports.
    data = build_json(turn, app_results, app_meta, kiro_results)
    json_path = os.path.join(out_dir, "evaluation.json")
    html_path = os.path.join(out_dir, "evaluation.html")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(data))

    # 5) Console summary.
    print("\n=== Application checks (independently rerun) ===")
    for r in app_results:
        print(f"  [{r.verdict:7}] {r.label}  expected={r.expected}  observed={r.observed}")
    print("\n=== Kiro execution checks (recorded) ===")
    for c in kiro_results:
        print(f"  [{c.verdict:7}] {c.title} — {c.summary}")

    print(f"\nReports written:\n  {json_path}\n  {html_path}")

    # 6) Exit code: the command must exit nonzero when any REQUIRED check is not
    # PASS (i.e. FAIL, BLOCKED, or UNKNOWN). All application checks and all Kiro
    # execution checks are treated as required. Missing evidence (UNKNOWN) is a
    # non-pass outcome by design and therefore also fails the run.
    all_verdicts = [r.verdict for r in app_results] + [c.verdict for c in kiro_results]
    non_pass = {v for v in all_verdicts if v != "PASS"}
    if not non_pass:
        print("\nOverall: PASS (all required checks passed) — exit 0")
        return 0
    # Deterministic, informative nonzero codes by worst severity present.
    severity = {"FAIL": 2, "BLOCKED": 3, "UNKNOWN": 4}
    worst = max(non_pass, key=lambda v: severity.get(v, 0))
    counts = {v: all_verdicts.count(v) for v in sorted(non_pass)}
    print(f"\nOverall: NOT PASS — {counts} — exiting {severity[worst]} (worst={worst})")
    return severity[worst]


if __name__ == "__main__":
    raise SystemExit(main())
