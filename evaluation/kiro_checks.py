"""Kiro-execution checks derived strictly from the recorded session turn.

These checks describe what Kiro *recorded* about the turn. They are kept separate
from the independent application re-check. Verdicts use PASS / FAIL / BLOCKED /
UNKNOWN; missing evidence never becomes PASS.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Optional

from config import (
    ALLOWED_EDIT_FILES,
    BACKEND_TEST_COUNT_CLAIM_REGEX,
    FILE_EDIT_TOOLS,
    PROJECT_ROOT,
    SHELL_TOOLS,
    TEST_COMMAND_MARKERS,
)
from session_reader import TurnData, ToolEvent


@dataclass
class CheckResult:
    key: str
    title: str
    verdict: str  # PASS | FAIL | BLOCKED | UNKNOWN
    summary: str
    evidence: list[str] = field(default_factory=list)


def _rel(path: str) -> str:
    p = path
    root = PROJECT_ROOT.rstrip("/") + "/"
    if p.startswith(root):
        return p[len(root):]
    return p


def _edit_events(turn: TurnData) -> list[ToolEvent]:
    return [e for e in turn.tool_events if e.tool_name in FILE_EDIT_TOOLS]


def _edit_path(ev: ToolEvent) -> Optional[str]:
    for key in ("path", "targetFile"):
        v = ev.args.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _shell_events(turn: TurnData) -> list[ToolEvent]:
    return [e for e in turn.tool_events if e.tool_name in SHELL_TOOLS]


# --- Real-outcome analysis for a recorded shell command ----------------------
#
# The guiding rule: the TOOL's success flag ("the wrapper ran") must NEVER be
# treated as the COMMAND's success ("the tests passed"). We derive the real
# outcome only from the recorded command output + its real exit code, and we
# fall back to UNKNOWN whenever the true exit status cannot be established.

# Signatures that a browser could not launch / a permission wall was hit. These
# are environmental BLOCKS, not application-test failures.
_LAUNCH_OR_PERMISSION_MARKERS = (
    "SIGSEGV",
    "SIGABRT",
    "browserType.launch",
    "Target page, context or browser has been closed",
    "Executable doesn't exist",
    "Failed to launch",
    "operation not permitted",
    "Operation not permitted",
    "EPERM",
)

# Pipes/redirections whose exit status replaces the test runner's own, so a
# trailing "Exit Code: 0" cannot be trusted to mean the tests passed.
_PIPE_MASK_MARKERS = ("| head", "| tail", "| grep", "| sed", "| awk", "| tee", "| cat", "|head", "|tail")


@dataclass
class ShellOutcome:
    verdict: str          # PASS | FAIL | BLOCKED | UNKNOWN
    reason: str
    exit_code: Optional[int]
    exit_trustworthy: bool
    passed: Optional[int] = None
    failed: Optional[int] = None


def _recorded_text(ev: ToolEvent) -> str:
    """Prefer the larger head+tail capture; fall back to the short excerpt."""
    return (ev.result_summary or ev.result_excerpt or "")


def _extract_exit_code(text: str) -> Optional[int]:
    m = re.search(r"Exit Code:\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


def _command_is_pipe_masked(cmd: str) -> bool:
    return any(mark in cmd for mark in _PIPE_MASK_MARKERS)


def analyze_shell_outcome(ev: ToolEvent, cmd: str) -> ShellOutcome:
    """Determine the REAL outcome of a recorded test command.

    Order of reasoning:
      1. If the output shows a browser-launch/permission failure -> BLOCKED,
         regardless of any exit code (the tests never actually ran).
      2. Otherwise, try to read the real test tally from the output
         (pytest "N passed/M failed", Playwright "N passed/failed").
      3. Consider the recorded exit code ONLY if it is trustworthy (the command
         did not pipe the runner's output into another process that would
         replace its exit status).
      4. If neither a trustworthy exit code nor a parseable tally is available,
         report UNKNOWN. The tool's success flag is never used as evidence.
    """
    text = _recorded_text(ev)
    exit_code = _extract_exit_code(text)
    pipe_masked = _command_is_pipe_masked(cmd)
    exit_trustworthy = exit_code is not None and not pipe_masked

    # 1. Environmental failure (browser launch / permissions) -> BLOCKED.
    for marker in _LAUNCH_OR_PERMISSION_MARKERS:
        if marker.lower() in text.lower():
            return ShellOutcome(
                "BLOCKED",
                f"browser-launch/permission failure detected ({marker!r}); tests did not run",
                exit_code, exit_trustworthy,
            )

    # 2. Parse a real test tally from the output.
    passed = failed = None
    mp = re.search(r"(\d+)\s+passed", text)
    mf = re.search(r"(\d+)\s+failed", text)
    if mp:
        passed = int(mp.group(1))
    if mf:
        failed = int(mf.group(1))

    if passed is not None or failed is not None:
        if (failed or 0) > 0:
            return ShellOutcome("FAIL", f"recorded tally shows {failed} failed", exit_code,
                                exit_trustworthy, passed, failed)
        # Zero failures AND a trustworthy exit 0 -> PASS; otherwise UNKNOWN.
        if exit_trustworthy and exit_code == 0:
            return ShellOutcome("PASS", f"recorded tally {passed} passed, 0 failed, exit 0",
                                exit_code, exit_trustworthy, passed, failed)
        if pipe_masked:
            return ShellOutcome("UNKNOWN",
                                f"tally shows {passed} passed but exit code is pipe-masked; cannot confirm",
                                exit_code, exit_trustworthy, passed, failed)
        return ShellOutcome("UNKNOWN",
                            f"tally shows {passed} passed but no trustworthy exit code",
                            exit_code, exit_trustworthy, passed, failed)

    # 3. No tally: rely on a trustworthy exit code if we have one.
    if exit_trustworthy:
        if exit_code == 0:
            return ShellOutcome("PASS", "exit 0 and no failure evidence", exit_code, True)
        return ShellOutcome("FAIL", f"nonzero exit code {exit_code}", exit_code, True)

    # 4. Nothing we can trust.
    return ShellOutcome("UNKNOWN",
                        "no parseable tally and exit code is absent or pipe-masked",
                        exit_code, False)


# --- Check 1: file-edit actions ----------------------------------------------

def check_file_edits(turn: TurnData) -> CheckResult:
    edits = _edit_events(turn)
    if not edits:
        return CheckResult(
            "file_edits", "File-edit actions recorded", "UNKNOWN",
            "No file-edit tool calls found in the selected turn.",
        )
    ev_lines, unresolved = [], 0
    for e in edits:
        path = _edit_path(e)
        if path is None:
            unresolved += 1
        succ = {True: "ok", False: "FAILED", None: "no-result"}[e.success]
        ev_lines.append(f"#{e.index} {e.tool_name} -> {_rel(path) if path else '<path not recorded>'} [{succ}]")
    verdict = "PASS" if unresolved == 0 else "UNKNOWN"
    summary = f"{len(edits)} file-edit action(s) recorded" + (
        f"; {unresolved} without a resolvable path" if unresolved else ""
    )
    return CheckResult("file_edits", "File-edit actions recorded", verdict, summary, ev_lines)


# --- Check 2: test commands and their recorded results -----------------------

def _aggregate(verdicts: list[str]) -> str:
    """Worst-wins aggregation; missing evidence never becomes PASS."""
    order = {"FAIL": 3, "BLOCKED": 2, "UNKNOWN": 1, "PASS": 0}
    if not verdicts:
        return "UNKNOWN"
    return max(verdicts, key=lambda v: order.get(v, 1))


def check_test_commands(turn: TurnData) -> CheckResult:
    """Verify each recorded test command by its REAL outcome, not the tool flag.

    A command being recorded (or the tool wrapper reporting success) is NOT
    evidence that the tests passed. We analyze the recorded output + real exit
    code, treat pipe-masked exit codes as unverifiable (UNKNOWN), and classify
    browser-launch/permission failures as BLOCKED rather than FAIL.
    """
    shell = _shell_events(turn)
    tests = []
    for e in shell:
        cmd = e.args.get("command", "")
        if isinstance(cmd, str) and any(m in cmd for m in TEST_COMMAND_MARKERS):
            tests.append((e, cmd))
    if not tests:
        return CheckResult(
            "test_commands", "Test commands verified by real outcome", "UNKNOWN",
            "No test-running commands found in the selected turn.",
        )

    ev_lines = []
    verdicts = []
    for e, cmd in tests:
        outcome = analyze_shell_outcome(e, cmd)
        verdicts.append(outcome.verdict)
        tool_flag = {True: "success", False: "failed", None: "no-result"}[e.success]
        ev_lines.append(
            f"#{e.index} `{cmd[:80]}`"
        )
        ev_lines.append(
            f"      -> verdict={outcome.verdict}; {outcome.reason} "
            f"(exit={outcome.exit_code}, trustworthy={outcome.exit_trustworthy}, "
            f"tool.success={tool_flag} [not used as proof])"
        )

    verdict = _aggregate(verdicts)
    summary = (
        f"{len(tests)} test command(s): "
        + ", ".join(f"{v}×{verdicts.count(v)}" for v in sorted(set(verdicts)))
    )
    return CheckResult("test_commands", "Test commands verified by real outcome",
                       verdict, summary, ev_lines)


# --- Check 3: edits outside allowed files ------------------------------------

def check_out_of_scope_edits(turn: TurnData) -> CheckResult:
    edits = _edit_events(turn)
    if not edits:
        return CheckResult(
            "scope", "Edits confined to allowed files", "UNKNOWN",
            "No file-edit actions recorded, so scope cannot be confirmed.",
        )
    out_of_scope, unresolved = [], 0
    touched = []
    for e in edits:
        path = _edit_path(e)
        if path is None:
            unresolved += 1
            continue
        rel = _rel(path)
        touched.append(rel)
        if rel not in ALLOWED_EDIT_FILES:
            out_of_scope.append(f"#{e.index} {e.tool_name} -> {rel}")
    distinct = sorted(set(touched))
    ev = [f"allowed files: {len(ALLOWED_EDIT_FILES)}",
          f"distinct files edited: {len(distinct)}"] + [f"  {p}" for p in distinct]
    if unresolved:
        return CheckResult(
            "scope", "Edits confined to allowed files", "UNKNOWN",
            f"{unresolved} edit(s) had no resolvable path; cannot fully confirm scope.",
            ev + [f"unresolved edits: {unresolved}"],
        )
    if out_of_scope:
        return CheckResult(
            "scope", "Edits confined to allowed files", "FAIL",
            f"{len(out_of_scope)} edit(s) outside the allowed set.",
            ev + ["OUT OF SCOPE:"] + ["  " + s for s in out_of_scope],
        )
    return CheckResult(
        "scope", "Edits confined to allowed files", "PASS",
        "All recorded edits fall within the allowed file set.", ev,
    )


# --- Check 4: failed actions and repeated commands ---------------------------

def check_failures_and_repeats(turn: TurnData) -> CheckResult:
    failed = [e for e in turn.tool_events if e.success is False]
    # Repeated shell commands (exact command text seen more than once).
    seen: dict[str, list[int]] = {}
    for e in _shell_events(turn):
        cmd = e.args.get("command")
        if isinstance(cmd, str):
            seen.setdefault(cmd.strip(), []).append(e.index)
    repeats = {c: idxs for c, idxs in seen.items() if len(idxs) > 1}

    ev = []
    if failed:
        ev.append(f"failed tool calls: {len(failed)}")
        for e in failed:
            ev.append(f"  #{e.index} {e.tool_name} -> {e.result_excerpt or '<no excerpt>'}")
    else:
        ev.append("failed tool calls: 0")

    if repeats:
        ev.append(f"repeated shell commands: {len(repeats)} (reported, not assumed defective)")
        for c, idxs in repeats.items():
            ev.append(f"  {idxs} `{c[:80]}`")
    else:
        ev.append("repeated shell commands: 0")

    # This check reports facts; it is PASS when the turn recorded no FAILED
    # actions, otherwise FAIL (a recorded failure is a real observed failure).
    # Repeats alone are reported, never auto-classified as defects.
    verdict = "PASS" if not failed else "FAIL"
    summary = (
        "No failed tool calls recorded"
        if not failed
        else f"{len(failed)} failed tool call(s) recorded"
    )
    if repeats:
        summary += f"; {len(repeats)} repeated command(s) reported for review"
    return CheckResult("failures_repeats", "Failed actions & repeated commands", verdict, summary, ev)


# --- Check 5: turn duration --------------------------------------------------

def _parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_duration(turn: TurnData) -> CheckResult:
    start, end = _parse_iso(turn.turn_start), _parse_iso(turn.turn_end)
    ev = []
    wall = None
    if start and end:
        wall = (end - start).total_seconds()
        ev.append(f"turn_start: {turn.turn_start}")
        ev.append(f"turn_end:   {turn.turn_end}")
        ev.append(f"wall-clock duration: {wall:.1f} s")
    else:
        ev.append("turn_start/turn_end not both present")
    if turn.usage_elapsed_ms is not None:
        ev.append(f"recorded usage_summary.elapsedTime: {turn.usage_elapsed_ms/1000:.1f} s")
    if wall is None and turn.usage_elapsed_ms is None:
        return CheckResult("duration", "Selected turn duration", "UNKNOWN",
                           "No timing evidence available.", ev)
    primary = wall if wall is not None else turn.usage_elapsed_ms / 1000
    return CheckResult("duration", "Selected turn duration", "PASS",
                       f"Turn duration ~{primary:.1f} s.", ev)


# --- Check 6: completion report vs. recorded evidence ------------------------

def check_report_vs_evidence(turn: TurnData) -> CheckResult:
    """Cross-check the report's explicit test-count / test-status claims.

    Only explicit, numeric claims are evaluated. Anything vague is UNKNOWN.
    """
    report = turn.report_text or ""
    ev = []

    # --- Backend pytest claim ---
    backend_claim = re.search(BACKEND_TEST_COUNT_CLAIM_REGEX, report)
    # Evidence: the recorded pytest result excerpt.
    pytest_ev = None
    for e in _shell_events(turn):
        cmd = e.args.get("command", "")
        if "pytest" in cmd:
            pytest_ev = e
            break

    backend_verdict = "UNKNOWN"
    if backend_claim is None:
        ev.append("backend claim: none explicit found -> UNKNOWN")
    elif pytest_ev is None or not (pytest_ev.result_summary or pytest_ev.result_excerpt):
        claimed_pass = backend_claim.group(1)
        ev.append(f"backend claim: '{claimed_pass} passed' but no recorded pytest result -> UNKNOWN")
    else:
        claimed_pass = int(backend_claim.group(1))
        claimed_fail = int(backend_claim.group(2)) if backend_claim.group(2) else 0
        # Use the longer head+tail capture so pytest's trailing summary line is
        # visible; fall back to the short excerpt if the summary is absent.
        recorded = pytest_ev.result_summary or pytest_ev.result_excerpt or ""
        m = re.search(r"(\d+)\s+passed", recorded)
        recorded_pass = int(m.group(1)) if m else None
        mf = re.search(r"(\d+)\s+failed", recorded)
        recorded_fail = int(mf.group(1)) if mf else 0
        ev.append(f"backend claim: {claimed_pass} passed, {claimed_fail} failed")
        ev.append(f"backend recorded: {recorded_pass} passed, {recorded_fail} failed (tool.success={pytest_ev.success})")
        if recorded_pass is None:
            backend_verdict = "UNKNOWN"
            ev.append("  -> recorded count not parseable -> UNKNOWN")
        elif claimed_pass == recorded_pass and claimed_fail == recorded_fail:
            backend_verdict = "PASS"
            ev.append("  -> claim matches recorded evidence")
        else:
            backend_verdict = "FAIL"
            ev.append("  -> claim DISAGREES with recorded evidence")

    # --- Playwright claim ---
    pw_ev = None
    for e in _shell_events(turn):
        if "playwright test" in e.args.get("command", ""):
            pw_ev = e
            break
    pw_verdict = "UNKNOWN"
    claims_blocked = bool(re.search(r"playwright[^.\n]*?(blocked|not run|SIGSEGV|segfault)", report, re.I)) \
        or bool(re.search(r"(blocked|not run)[^.\n]*playwright", report, re.I))
    if pw_ev is None:
        ev.append("playwright claim: no recorded playwright command -> UNKNOWN")
    else:
        rec = (pw_ev.result_excerpt or "")
        rec_blocked = bool(re.search(r"SIGSEGV|segv|browser has been closed|Target page", rec, re.I))
        ev.append(f"playwright claimed-blocked={claims_blocked}; recorded-launch-failure={rec_blocked}")
        if claims_blocked and rec_blocked:
            pw_verdict = "PASS"
            ev.append("  -> report's 'blocked' claim matches recorded browser-launch failure")
        elif not claims_blocked:
            pw_verdict = "UNKNOWN"
            ev.append("  -> report makes no explicit, unambiguous playwright status claim -> UNKNOWN")
        else:
            pw_verdict = "FAIL"
            ev.append("  -> report claims blocked but evidence does not show a launch failure")

    # Combine: the check is PASS only if every explicit claim evaluated is PASS;
    # any FAIL -> FAIL; otherwise if any UNKNOWN and no FAIL -> UNKNOWN.
    sub = [backend_verdict, pw_verdict]
    if "FAIL" in sub:
        overall = "FAIL"
    elif all(v == "PASS" for v in sub):
        overall = "PASS"
    else:
        overall = "UNKNOWN"
    summary = f"backend-claim={backend_verdict}, playwright-claim={pw_verdict}"
    return CheckResult("report_vs_evidence", "Completion report vs. recorded evidence",
                       overall, summary, ev)


def run_all_kiro_checks(turn: TurnData) -> list[CheckResult]:
    return [
        check_file_edits(turn),
        check_test_commands(turn),
        check_out_of_scope_edits(turn),
        check_failures_and_repeats(turn),
        check_duration(turn),
        check_report_vs_evidence(turn),
    ]
