#!/usr/bin/env python3
"""Validate the evaluator with TEMPORARY fixtures.

Proves the evaluator's negative controls without touching the real session log,
application code, existing tests, or the original expectations in config.py:

  A. One incorrect expected application outcome -> that check is FAIL (exit 2).
  B. Missing report evidence -> report-vs-evidence check is UNKNOWN (exit 4).
  C. A test command that actually FAILED is FAIL, even though the tool wrapper
     reported success (tool.success must never be read as command success).
  D. A test command with NO recorded result is UNKNOWN, never PASS.
  E. The real historical trap: tool.success=True AND a pipe-masked "Exit Code: 0"
     while the output shows a browser-launch failure -> BLOCKED, not PASS.
  F. A passing-looking tally with a pipe-masked exit code -> UNKNOWN (unverifiable).
  G. Positive control: a clean passing run (trustworthy exit 0, no pipe) -> PASS.

All fixtures are constructed in memory / under temp directories and discarded.
This script is a harness self-test; it is not part of a normal evaluation run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from session_reader import load_turn  # noqa: E402
import kiro_checks  # noqa: E402
import app_recheck  # noqa: E402
import report as report_mod  # noqa: E402
from app_recheck import AppCheckResult  # noqa: E402
from ui_checks import UIResult  # noqa: E402


def _severity_exit(verdicts: list[str]) -> int:
    non_pass = {v for v in verdicts if v != "PASS"}
    if not non_pass:
        return 0
    sev = {"FAIL": 2, "BLOCKED": 3, "UNKNOWN": 4}
    return sev[max(non_pass, key=lambda v: sev.get(v, 0))]


def case_a_incorrect_expectation() -> bool:
    """Flip ONE expected outcome to a wrong value (in a temporary copy of the
    matrix) and confirm the app re-check reports FAIL for exactly that row."""
    print("\n[Case A] incorrect expected application outcome -> expect FAIL")
    original = list(config.APP_CHECKS)
    try:
        # Temporarily assert normal qty 60 should be REJECTED (it should be PAID).
        bad = ("[FIXTURE] normal qty 60 -> wrongly expect REJECTED",
               "DRUG-001", 60, 200, "REJECTED", "QUANTITY_LIMIT_EXCEEDED")
        config.APP_CHECKS = [bad]
        app_recheck.APP_CHECKS = config.APP_CHECKS  # module imported the list by value
        results, meta = app_recheck.run_app_checks()
        for r in results:
            print(f"    [{r.verdict}] {r.label}  expected={r.expected} observed={r.observed}")
        if not meta.get("started"):
            print("    INCONCLUSIVE: backend did not start; cannot prove FAIL vs BLOCKED.")
            return False
        verdict = results[0].verdict
        exit_code = _severity_exit([r.verdict for r in results])
        ok = verdict == "FAIL" and exit_code == 2
        print(f"    -> verdict={verdict}, aggregate exit={exit_code}  ::  {'OK' if ok else 'UNEXPECTED'}")
        return ok
    finally:
        config.APP_CHECKS = original
        app_recheck.APP_CHECKS = original


def case_b_missing_evidence() -> bool:
    """Build a tiny synthetic session fixture where the turn has a completion
    report claiming '20 passed' but NO recorded pytest result, and confirm the
    report-vs-evidence check is UNKNOWN."""
    print("\n[Case B] missing test-result evidence -> expect UNKNOWN")
    eid = "FIXTURE-exec-0001"
    # Minimal event stream: user prompt, turn_start, an assistant report that
    # makes an explicit backend claim, a pytest tool_call WITHOUT a tool_result,
    # and turn_end. No tool_result => evidence is missing.
    events = [
        {"id": "1", "timestamp": "2026-01-01T00:00:00.000Z",
         "payload": {"type": "user", "content": config.TARGET_PROMPT_PREFIX + " ..."}},
        {"id": "2", "timestamp": "2026-01-01T00:00:00.100Z",
         "payload": {"type": "turn_start", "executionId": eid}},
        {"id": "3", "timestamp": "2026-01-01T00:00:01.000Z",
         "payload": {"type": "assistant", "executionId": eid,
                     "content": "Backend: 20 passed, 0 failed. Done."}},
        {"id": "4", "timestamp": "2026-01-01T00:00:02.000Z",
         "payload": {"type": "tool_call", "executionId": eid, "toolCallId": "tc1",
                     "toolName": "execute_bash", "actionType": "run_command",
                     "args": {"command": ".venv/bin/python -m pytest"}, "status": "completed"}},
        # NOTE: deliberately NO tool_result for tc1 (missing evidence).
        {"id": "5", "timestamp": "2026-01-01T00:01:00.000Z",
         "payload": {"type": "turn_end", "executionId": eid, "stopReason": "end_turn"}},
    ]
    with tempfile.TemporaryDirectory() as td:
        fixture = os.path.join(td, "messages.jsonl")
        with open(fixture, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        turn = load_turn(fixture, eid, config.TARGET_PROMPT_PREFIX)
        check = kiro_checks.check_report_vs_evidence(turn)
        for line in check.evidence:
            print("    ", line)
        exit_code = _severity_exit([check.verdict])
        ok = check.verdict == "UNKNOWN" and exit_code == 4
        print(f"    -> verdict={check.verdict}, aggregate exit={exit_code}  ::  {'OK' if ok else 'UNEXPECTED'}")
        return ok


def _turn_with_test_command(cmd: str, result_content, tool_success) -> "kiro_checks.TurnData":
    """Build a synthetic one-command turn fixture and load it as a TurnData.

    ``result_content`` of None means NO tool_result was recorded (missing result).
    ``tool_success`` is the (possibly misleading) wrapper success flag.
    """
    eid = "FIXTURE-cmd-0001"
    events = [
        {"id": "1", "timestamp": "2026-01-01T00:00:00.000Z",
         "payload": {"type": "user", "content": config.TARGET_PROMPT_PREFIX + " ..."}},
        {"id": "2", "timestamp": "2026-01-01T00:00:00.100Z",
         "payload": {"type": "turn_start", "executionId": eid}},
        {"id": "3", "timestamp": "2026-01-01T00:00:01.000Z",
         "payload": {"type": "tool_call", "executionId": eid, "toolCallId": "tc1",
                     "toolName": "execute_bash", "actionType": "run_command",
                     "args": {"command": cmd}, "status": "completed"}},
    ]
    if result_content is not None:
        events.append(
            {"id": "4", "timestamp": "2026-01-01T00:00:02.000Z",
             "payload": {"type": "tool_result", "executionId": eid, "toolCallId": "tc1",
                         "success": tool_success, "content": result_content}})
    events.append(
        {"id": "5", "timestamp": "2026-01-01T00:01:00.000Z",
         "payload": {"type": "turn_end", "executionId": eid, "stopReason": "end_turn"}})

    import shutil
    td = tempfile.mkdtemp()
    try:
        fixture = os.path.join(td, "messages.jsonl")
        with open(fixture, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return load_turn(fixture, eid, config.TARGET_PROMPT_PREFIX)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def case_c_failed_command() -> bool:
    """A test command that actually FAILED (nonzero exit + failed tally) must be
    FAIL, even though the tool wrapper reported success."""
    print("\n[Case C] failed test command (misleading tool.success=True) -> expect FAIL")
    content = (
        "Output:\n==== test session starts ====\n"
        "tests/test_rules.py::test_x FAILED\n"
        "==== 1 failed, 19 passed in 0.3s ====\n\nExit Code: 1"
    )
    turn = _turn_with_test_command(".venv/bin/python -m pytest", content, tool_success=True)
    check = kiro_checks.check_test_commands(turn)
    for line in check.evidence:
        print("    ", line)
    ok = check.verdict == "FAIL"
    print(f"    -> verdict={check.verdict}  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def case_d_missing_result() -> bool:
    """A test command with NO recorded tool_result must be UNKNOWN (never PASS)."""
    print("\n[Case D] test command with missing result -> expect UNKNOWN")
    turn = _turn_with_test_command("npx playwright test", result_content=None, tool_success=True)
    check = kiro_checks.check_test_commands(turn)
    for line in check.evidence:
        print("    ", line)
    ok = check.verdict == "UNKNOWN"
    print(f"    -> verdict={check.verdict}  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def case_e_misleading_success_pipe_masked() -> bool:
    """The real historical trap: tool.success=True AND 'Exit Code: 0' (because the
    command piped into `head`), but the output shows a browser-launch failure.
    Must be BLOCKED (environmental), NOT PASS."""
    print("\n[Case E] misleading success (pipe-masked exit 0 + launch failure) -> expect BLOCKED")
    content = (
        "Output:\nRunning 3 tests using 1 worker\n"
        "Error: browserType.launch: Target page, context or browser has been closed\n"
        "[pid=123][err] Received signal 11 SEGV_ACCERR\n\nExit Code: 0"
    )
    turn = _turn_with_test_command("npx playwright test --reporter=line 2>&1 | head -40",
                                   content, tool_success=True)
    check = kiro_checks.check_test_commands(turn)
    for line in check.evidence:
        print("    ", line)
    ok = check.verdict == "BLOCKED"
    print(f"    -> verdict={check.verdict}  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def case_f_pipe_masked_pass_is_unknown() -> bool:
    """A passing-looking tally but a pipe-masked exit code cannot be confirmed as
    PASS -> UNKNOWN (missing/unverifiable evidence never becomes PASS)."""
    print("\n[Case F] passing tally but pipe-masked exit -> expect UNKNOWN")
    content = (
        "Output:\nRunning 3 tests using 1 worker\n  3 passed (1.9s)\n\nExit Code: 0"
    )
    turn = _turn_with_test_command("npx playwright test --reporter=line 2>&1 | head -40",
                                   content, tool_success=True)
    check = kiro_checks.check_test_commands(turn)
    for line in check.evidence:
        print("    ", line)
    ok = check.verdict == "UNKNOWN"
    print(f"    -> verdict={check.verdict}  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def case_g_clean_pass() -> bool:
    """Positive control: a clean pytest run (trustworthy exit 0 + passing tally,
    no pipe) must still be PASS, so the stricter rules are not over-zealous."""
    print("\n[Case G] clean passing run (no pipe, exit 0) -> expect PASS")
    content = "Output:\n==== 20 passed, 1 warning in 0.26s ====\n\nExit Code: 0"
    turn = _turn_with_test_command(".venv/bin/python -m pytest", content, tool_success=True)
    check = kiro_checks.check_test_commands(turn)
    for line in check.evidence:
        print("    ", line)
    ok = check.verdict == "PASS"
    print(f"    -> verdict={check.verdict}  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


class _FakeCheck:
    """Minimal stand-in with a .verdict attribute for verdict-aggregation tests."""
    def __init__(self, verdict):
        self.verdict = verdict


def case_h_historical_block_cannot_hide_current_failure() -> bool:
    """Separation regression #1: a HISTORICAL BLOCKED must not hide a CURRENT
    application FAIL. The current verdict must reflect the app failure; the
    historical verdict stays BLOCKED; they are reported independently."""
    print("\n[Case H] historical BLOCKED must not hide a current app FAILURE")
    # Current app results: one FAIL (e.g. an adjudication regression). UI PASS.
    app_results = [
        AppCheckResult("normal qty 60 -> PAID", "FAIL", "PAID", "REJECTED"),
        AppCheckResult("qty 0 -> HTTP 422", "PASS", "HTTP 422", "HTTP 422"),
    ]
    ui = UIResult("PASS", "3/3 UI tests passed", exit_code=0, passed=3, failed=0)
    # Historical recorded execution: BLOCKED (the real original Playwright block).
    kiro = [_FakeCheck("BLOCKED"), _FakeCheck("PASS")]

    current = report_mod.current_application_verdict(app_results, ui)
    historical = report_mod.historical_execution_verdict(kiro)
    current_code = _severity_exit([r.verdict for r in app_results] + [ui.verdict])
    print(f"    current={current} (exit {current_code}), historical={historical}")
    ok = current == "FAIL" and current_code == 2 and historical == "BLOCKED"
    print(f"    -> current surfaces FAIL, historical stays BLOCKED  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def case_i_current_pass_cannot_erase_historical_failure() -> bool:
    """Separation regression #2: a CURRENT all-PASS must not erase a HISTORICAL
    failure. Current verdict is PASS (exit 0); historical verdict remains
    BLOCKED and is never forced to PASS."""
    print("\n[Case I] current PASS must not erase the historical failure")
    app_results = [
        AppCheckResult("normal qty 60 -> PAID", "PASS", "PAID", "PAID"),
        AppCheckResult("qty 0 -> HTTP 422", "PASS", "HTTP 422", "HTTP 422"),
        AppCheckResult("FE->BE connectivity + CORS", "PASS", "ok", "ok"),
    ]
    ui = UIResult("PASS", "3/3 UI tests passed", exit_code=0, passed=3, failed=0)
    kiro = [_FakeCheck("BLOCKED"), _FakeCheck("PASS")]  # historical still BLOCKED

    current = report_mod.current_application_verdict(app_results, ui)
    historical = report_mod.historical_execution_verdict(kiro)
    current_code = _severity_exit([r.verdict for r in app_results] + [ui.verdict])
    historical_code = _severity_exit([c.verdict for c in kiro])
    print(f"    current={current} (exit {current_code}), historical={historical} (gate exit {historical_code})")
    ok = (current == "PASS" and current_code == 0
          and historical == "BLOCKED" and historical_code == 3)
    print(f"    -> current PASS/exit0 while historical stays BLOCKED/exit3  ::  {'OK' if ok else 'UNEXPECTED'}")
    return ok


def main() -> int:
    a = case_a_incorrect_expectation()
    b = case_b_missing_evidence()
    c = case_c_failed_command()
    d = case_d_missing_result()
    e = case_e_misleading_success_pipe_masked()
    f = case_f_pipe_masked_pass_is_unknown()
    g = case_g_clean_pass()
    h = case_h_historical_block_cannot_hide_current_failure()
    i = case_i_current_pass_cannot_erase_historical_failure()
    print("\n=== validation summary ===")
    print(f"  Case A (incorrect expectation -> FAIL, exit 2):          {'OK' if a else 'FAILED'}")
    print(f"  Case B (missing report evidence -> UNKNOWN, exit 4):     {'OK' if b else 'FAILED'}")
    print(f"  Case C (failed command despite tool.success -> FAIL):    {'OK' if c else 'FAILED'}")
    print(f"  Case D (missing command result -> UNKNOWN):              {'OK' if d else 'FAILED'}")
    print(f"  Case E (pipe-masked exit + launch fail -> BLOCKED):      {'OK' if e else 'FAILED'}")
    print(f"  Case F (pipe-masked passing tally -> UNKNOWN):           {'OK' if f else 'FAILED'}")
    print(f"  Case G (clean pass control -> PASS):                     {'OK' if g else 'FAILED'}")
    print(f"  Case H (historical BLOCKED can't hide current FAIL):     {'OK' if h else 'FAILED'}")
    print(f"  Case I (current PASS can't erase historical failure):    {'OK' if i else 'FAILED'}")
    print("\nReal session log, application, and original expectations unchanged.")
    return 0 if all((a, b, c, d, e, f, g, h, i)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
