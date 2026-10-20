"""UI checks: run the existing Playwright specs against the fresh frontend.

Honesty guarantees required by the task:
  * PASS requires BOTH the real `npx playwright test` exit code == 0 AND valid
    structured test-result evidence (the JSON reporter output) showing the
    expected tests passed. Either missing -> not PASS.
  * A browser-launch failure (segfault / "browser has been closed" / missing
    browser) is reported BLOCKED with the real failure evidence, never PASS.
  * We capture the actual child exit code; a zero wrapper status with failing
    tests still yields FAIL.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from config import (
    E2E_DIR,
    EXPECTED_PLAYWRIGHT_TESTS,
    PLAYWRIGHT_TIMEOUT_S,
    SYSTEM_CHROME_CANDIDATES,
)

# Signatures that indicate the browser could not launch (environmental BLOCK).
_LAUNCH_FAILURE_MARKERS = (
    "SIGSEGV",
    "SIGABRT",
    "Target page, context or browser has been closed",
    "browserType.launch",
    "Executable doesn't exist",
    "Failed to launch",
    "no such file or directory",
)


@dataclass
class UIResult:
    verdict: str  # PASS | FAIL | BLOCKED | UNKNOWN
    summary: str
    exit_code: Optional[int] = None
    expected_tests: int = EXPECTED_PLAYWRIGHT_TESTS
    passed: Optional[int] = None
    failed: Optional[int] = None
    evidence: list[str] = field(default_factory=list)
    per_test: list[dict] = field(default_factory=list)


def _discover_chrome() -> Optional[str]:
    for p in SYSTEM_CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _parse_json_report(path: str) -> tuple[Optional[int], Optional[int], list[dict], str]:
    """Return (passed, failed, per_test, error_text) from a Playwright JSON report.

    Uses Playwright's own ``stats`` block (expected/unexpected/flaky) as the
    authoritative tally, and walks ``specs`` for per-test titles and error text.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None, [], ""

    per_test: list[dict] = []
    error_parts: list[str] = []

    def walk(suite: dict):
        for spec in suite.get("specs", []):
            title = spec.get("title", "<spec>")
            ok = spec.get("ok", False)
            for t in spec.get("tests", []):
                for r in t.get("results", []):
                    for err in r.get("errors", []) or []:
                        msg = err.get("message") or ""
                        if msg:
                            error_parts.append(msg)
                    if isinstance(r.get("error"), dict) and r["error"].get("message"):
                        error_parts.append(r["error"]["message"])
            per_test.append({"title": title, "ok": bool(ok)})
        for child in suite.get("suites", []):
            walk(child)

    for suite in data.get("suites", []):
        walk(suite)

    # Authoritative counts from stats when present.
    stats = data.get("stats") or {}
    if "expected" in stats or "unexpected" in stats:
        passed = int(stats.get("expected", 0))
        failed = int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0))
    else:
        passed = sum(1 for t in per_test if t["ok"])
        failed = sum(1 for t in per_test if not t["ok"])
    return passed, failed, per_test, "\n".join(error_parts)


def run_ui_checks(frontend_base_url: str) -> UIResult:
    """Run Playwright against ``frontend_base_url`` and classify the outcome."""
    chrome = _discover_chrome()
    report_fd, report_path = tempfile.mkstemp(prefix="pw-report-", suffix=".json")
    os.close(report_fd)

    env = dict(os.environ)
    env["BASE_URL"] = frontend_base_url
    env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = report_path
    if chrome:
        env["PW_CHROME_PATH"] = chrome

    cmd = ["npx", "playwright", "test", "--reporter=json"]
    evidence: list[str] = [f"command: BASE_URL={frontend_base_url} npx playwright test"]
    if chrome:
        evidence.append(f"PW_CHROME_PATH={chrome}")
    else:
        evidence.append("PW_CHROME_PATH not set (no system Chrome found; using bundled browser)")

    try:
        proc = subprocess.run(
            cmd,
            cwd=E2E_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=PLAYWRIGHT_TIMEOUT_S,
        )
        exit_code = proc.returncode
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        evidence.append(f"playwright timed out after {PLAYWRIGHT_TIMEOUT_S}s")
        return UIResult("BLOCKED", "Playwright timed out", exit_code=None, evidence=evidence)
    except FileNotFoundError:
        evidence.append("npx not found on PATH — cannot run Playwright")
        return UIResult("BLOCKED", "npx/playwright not available", exit_code=None, evidence=evidence)
    finally:
        pass

    evidence.append(f"actual child exit code: {exit_code}")

    passed, failed, per_test, report_launch_text = _parse_json_report(report_path)
    try:
        os.remove(report_path)
    except OSError:
        pass

    # Detect browser-launch failure first (environmental BLOCK, not FAIL/PASS).
    launch_haystack = combined + "\n" + (report_launch_text or "")
    launch_failed = any(m.lower() in launch_haystack.lower() for m in _LAUNCH_FAILURE_MARKERS)

    if launch_failed:
        # Pull a short, real evidence line from the failure text.
        snippet = ""
        for marker in _LAUNCH_FAILURE_MARKERS:
            idx = launch_haystack.lower().find(marker.lower())
            if idx != -1:
                snippet = " ".join(launch_haystack[idx: idx + 160].split())
                break
        evidence.append(f"launch-failure evidence: {snippet}")
        return UIResult(
            "BLOCKED",
            "Playwright browser could not launch (environmental)",
            exit_code=exit_code,
            passed=passed,
            failed=failed,
            evidence=evidence,
            per_test=per_test,
        )

    # No evidence at all (no JSON parsed) -> cannot confirm -> UNKNOWN.
    if passed is None and failed is None:
        evidence.append("no structured test-result evidence found in JSON report")
        return UIResult("UNKNOWN", "No Playwright result evidence", exit_code=exit_code, evidence=evidence)

    evidence.append(f"evidence: passed={passed}, failed={failed}, expected={EXPECTED_PLAYWRIGHT_TESTS}")
    for t in per_test:
        evidence.append(f"  {'ok' if t['ok'] else 'FAIL'}: {t['title']}")
    if failed and report_launch_text:
        first_err = " ".join(report_launch_text.split())[:200]
        evidence.append(f"first error: {first_err}")

    # PASS requires BOTH: real exit code 0 AND evidence of the expected number of
    # passing tests with zero failures.
    if exit_code == 0 and failed == 0 and passed == EXPECTED_PLAYWRIGHT_TESTS:
        return UIResult("PASS", f"{passed}/{EXPECTED_PLAYWRIGHT_TESTS} UI tests passed",
                        exit_code=exit_code, passed=passed, failed=failed,
                        evidence=evidence, per_test=per_test)

    # Exit code 0 but evidence disagrees (e.g. fewer tests ran) -> do not trust the
    # wrapper; treat as FAIL/UNKNOWN per the mismatch.
    if exit_code == 0 and (failed == 0) and passed != EXPECTED_PLAYWRIGHT_TESTS:
        evidence.append("exit code 0 but passing-test count != expected -> not PASS")
        return UIResult("UNKNOWN", "Exit 0 but test count mismatch",
                        exit_code=exit_code, passed=passed, failed=failed,
                        evidence=evidence, per_test=per_test)

    return UIResult("FAIL", f"UI tests failed ({failed} failed, {passed} passed)",
                    exit_code=exit_code, passed=passed, failed=failed,
                    evidence=evidence, per_test=per_test)
