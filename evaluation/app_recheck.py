"""Independently re-run the application checks against a FRESH backend.

This is the "independently rerun" half of the evaluation, kept strictly separate
from anything the session log recorded. It:

  1. spawns uvicorn from THIS checkout on a dedicated port,
  2. waits for health,
  3. posts each claim in the matrix and compares the response,
  4. tears the process down (even on failure),

and returns structured results. It never touches application code or tests; it
only runs the app as a black box over HTTP.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from config import (
    APP_CHECKS,
    BACKEND_HOST,
    BACKEND_PORT,
    BACKEND_STARTUP_TIMEOUT_S,
    PROJECT_ROOT,
)


@dataclass
class AppCheckResult:
    label: str
    verdict: str  # PASS | FAIL | BLOCKED
    expected: str
    observed: str
    detail: str = ""


def _backend_dir() -> str:
    return os.path.join(PROJECT_ROOT, "backend")


def _python_exe() -> Optional[str]:
    """Prefer the backend venv interpreter; fall back to the current one."""
    venv_py = os.path.join(_backend_dir(), ".venv", "bin", "python")
    if os.path.exists(venv_py):
        return venv_py
    return sys.executable or None


def _wait_for_health(base: str, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.4)
    return False


def _post_claim(base: str, drug_id: str, quantity: int):
    """POST a claim; return (http_status, body_dict_or_None)."""
    payload = {
        "memberId": "M1001",
        "drugId": drug_id,
        "quantity": quantity,
        "submittedAmount": 42.5,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}/api/claims", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def run_matrix_against(base_url: str) -> list[AppCheckResult]:
    """Run the adjudication matrix against an ALREADY-RUNNING backend at ``base_url``.

    Used by the full orchestrator, which owns the backend process lifecycle. This
    function neither spawns nor stops any process.
    """
    results: list[AppCheckResult] = []
    for (label, drug, qty, exp_http, exp_status, exp_reason) in APP_CHECKS:
        status, body = _post_claim(base_url, drug, qty)
        if exp_http == 422:
            expected = "HTTP 422"
            observed = f"HTTP {status}"
            verdict = "PASS" if status == 422 else "FAIL"
            results.append(AppCheckResult(label, verdict, expected, observed))
            continue

        got_status = (body or {}).get("status")
        got_reason = (body or {}).get("reasonCode")
        expected = f"HTTP {exp_http} / {exp_status}" + (f" / {exp_reason}" if exp_reason else "")
        observed = f"HTTP {status} / {got_status}" + (f" / {got_reason}" if got_reason else "")
        ok = status == exp_http and got_status == exp_status and (
            exp_reason is None or got_reason == exp_reason
        )
        results.append(AppCheckResult(label, "PASS" if ok else "FAIL", expected, observed))
    return results


def blocked_matrix(reason: str) -> list[AppCheckResult]:
    """Return a BLOCKED result for every app check (used when backend is unavailable)."""
    return [AppCheckResult(lbl, "BLOCKED", "n/a", "n/a", reason) for (lbl, *_rest) in APP_CHECKS]


def run_app_checks() -> tuple[list[AppCheckResult], dict]:
    """Spawn a fresh backend, run the matrix, clean up. Returns (results, meta).

    Retained for the existing standalone ``evaluate.py`` (turn-only evaluator). The
    full orchestrator uses ``run_matrix_against`` with its own managed backend.
    """
    meta = {
        "port": BACKEND_PORT,
        "host": BACKEND_HOST,
        "started": False,
        "python": _python_exe(),
        "note": "",
    }
    py = _python_exe()
    if not py:
        return blocked_matrix("no python interpreter"), {**meta, "note": "no python interpreter available"}

    base = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    cmd = [py, "-m", "uvicorn", "app.main:app", "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)]
    proc = subprocess.Popen(
        cmd,
        cwd=_backend_dir(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if not _wait_for_health(base, BACKEND_STARTUP_TIMEOUT_S):
            meta["note"] = "backend did not become healthy within timeout"
            return blocked_matrix("backend unavailable"), meta
        meta["started"] = True
        return run_matrix_against(base), meta
    finally:
        # Deterministic cleanup regardless of outcome.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass
