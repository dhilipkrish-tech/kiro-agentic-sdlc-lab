#!/usr/bin/env python3
"""Full evaluation orchestrator — ONE command, end to end.

Pipeline (all from this checkout, isolated from your dev environment):

  1. allocate free ephemeral ports for backend + frontend (race-safe)
  2. start a fresh backend, wait for real HTTP /api/health
  3. start a fresh frontend pointed at that backend (VITE_API_BASE)
  4. wait for the frontend to actually serve, verify FE->BE connectivity + CORS
  5. run the existing backend/application adjudication matrix
  6. run the existing 3 Playwright UI tests against the fresh frontend
  7. evaluate the recorded Kiro requirement-change turn (unchanged)
  8. write ONE combined JSON + HTML report (even if a stage fails)
  9. exit nonzero if any REQUIRED check is FAIL/BLOCKED/UNKNOWN
 10. always terminate ONLY the processes this run started (incl. on interrupt)

Does not modify application code/behavior or weaken tests. Never adopts an
already-running server: if an allocated port is taken at bind time, it re-picks;
servers are addressed by the exact port we launched.

Single command:
    python3 evaluation/run_full_eval.py
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from session_reader import find_current_session_log, load_turn  # noqa: E402
from kiro_checks import run_all_kiro_checks  # noqa: E402
from app_recheck import run_matrix_against, blocked_matrix, _python_exe  # noqa: E402
from ui_checks import run_ui_checks  # noqa: E402
from report import build_html, build_json  # noqa: E402


# --- process registry (only what WE start) -----------------------------------

_STARTED: list[subprocess.Popen] = []
_LOG_FILES: dict[int, str] = {}  # pid -> temp log path (for evidence + cleanup)
_CLEANED = False


def _spawn(cmd: list[str], cwd: str, env: dict | None = None, tag: str = "srv") -> subprocess.Popen:
    """Start a server in its own process group, with output to a temp log FILE.

    Writing to a file (not a PIPE) is essential: uvicorn/vite emit request logs
    during the Playwright run, and an undrained PIPE would fill its OS buffer and
    STALL the server mid-test. A file never blocks the writer.
    """
    fd, log_path = tempfile.mkstemp(prefix=f"eval-{tag}-", suffix=".log")
    log_fh = os.fdopen(fd, "w")
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=log_fh, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    _STARTED.append(proc)
    _LOG_FILES[proc.pid] = log_path
    return proc


def _reserve_free_port() -> int:
    """Reserve a free TCP port by binding to 0, then releasing it.

    There is an inherent TOCTOU window between releasing and a child re-binding;
    we close that by (a) asking the child to bind this exact port and (b) treating
    a bind failure as a start failure (re-pick), never as "reuse whatever's there".
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((config.LOOPBACK, 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _port_is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((config.LOOPBACK, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def cleanup() -> None:
    """Terminate every process group we started. Idempotent; safe on any exit."""
    global _CLEANED
    if _CLEANED:
        return
    _CLEANED = True
    for proc in reversed(_STARTED):
        if proc.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except Exception:
                pass
    # Give them a moment, then hard-kill stragglers.
    deadline = time.time() + 8
    for proc in reversed(_STARTED):
        remaining = max(0.0, deadline - time.time())
        try:
            proc.wait(timeout=remaining or 0.1)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    # Remove temp server log files.
    for path in _LOG_FILES.values():
        try:
            os.remove(path)
        except OSError:
            pass


def _install_signal_handlers() -> None:
    def handler(signum, frame):
        cleanup()
        # Re-raise default behavior so the shell sees an interrupted exit.
        raise SystemExit(130 if signum == signal.SIGINT else 143)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass
    atexit.register(cleanup)


# --- readiness probes ---------------------------------------------------------

def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError):
        return False


def _wait_until(url: str, timeout_s: float, proc: subprocess.Popen) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # process died during startup
        if _http_ok(url):
            return True
        time.sleep(0.4)
    return False


def _fetch_text(url: str, timeout: float = 3.0) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if 200 <= r.status < 400:
                return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None
    return None


def _wait_frontend_ready(base: str, timeout_s: float, proc: subprocess.Popen) -> tuple[bool, str]:
    """Prove the frontend is genuinely ready, not just that the HTTP port answers.

    Vite returns 200 on `/` before it finishes dependency pre-bundling, so a bare
    200 can precede a working app and flake the first navigation. We additionally:
      * confirm the served index references the app entry module, and
      * warm up that entry module (forcing Vite to pre-bundle) until it serves,
    then add a short settle.
    """
    deadline = time.time() + timeout_s
    entry = None
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, "frontend process exited during startup"
        html_text = _fetch_text(f"{base}/")
        if html_text:
            # Find the module entry referenced by the index (e.g. /src/main.jsx).
            if entry is None:
                import re as _re
                m = _re.search(r'src="(/[^"]+\.(?:jsx?|tsx?|mjs))"', html_text)
                entry = m.group(1) if m else "/src/main.jsx"
            mod = _fetch_text(f"{base}{entry}")
            if mod is not None and ("import" in mod or "React" in mod or len(mod) > 0):
                time.sleep(1.0)  # brief settle so the dev server is steady
                return True, f"index + entry module {entry} served"
        time.sleep(0.4)
    return False, "frontend did not become fully ready within timeout"


def _drain(proc: subprocess.Popen, limit: int = 1500) -> str:
    """Best-effort capture of a process's log file for evidence (non-blocking)."""
    path = _LOG_FILES.get(proc.pid)
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        return data[-limit:]
    except OSError:
        return ""


# --- backend / frontend starters ---------------------------------------------

def start_backend() -> tuple[subprocess.Popen | None, int, str, str]:
    """Return (proc, port, base_url, note)."""
    py = _python_exe()
    if not py:
        return None, 0, "", "no python interpreter available"
    for _ in range(5):
        port = _reserve_free_port()
        if not _port_is_free(port):
            continue
        base = f"http://{config.LOOPBACK}:{port}"
        proc = _spawn(
            [py, "-m", "uvicorn", "app.main:app", "--host", config.LOOPBACK, "--port", str(port)],
            cwd=config.BACKEND_DIR, tag="backend",
        )
        if _wait_until(f"{base}/api/health", config.BACKEND_READY_TIMEOUT_S, proc):
            return proc, port, base, ""
        # failed to become ready — capture evidence, don't adopt anything
        note = f"backend not ready; output: {_drain(proc)}"
        return proc, port, base, note
    return None, 0, "", "could not allocate a free backend port"


def start_frontend(backend_base: str) -> tuple[subprocess.Popen | None, int, str, str]:
    """Return (proc, port, base_url, note). Points the UI at ``backend_base``."""
    for _ in range(5):
        port = _reserve_free_port()
        if not _port_is_free(port):
            continue
        base = f"http://{config.LOOPBACK}:{port}"
        env = dict(os.environ)
        env["VITE_API_BASE"] = backend_base  # UI talks to OUR isolated backend
        proc = _spawn(
            ["npm", "run", "dev", "--", "--port", str(port), "--strictPort", "--host", config.LOOPBACK],
            cwd=config.FRONTEND_DIR, env=env, tag="frontend",
        )
        ready, detail = _wait_frontend_ready(base, config.FRONTEND_READY_TIMEOUT_S, proc)
        if ready:
            return proc, port, base, ""
        note = f"frontend not ready ({detail}); output: {_drain(proc)}"
        return proc, port, base, note
    return None, 0, "", "could not allocate a free frontend port"


# --- FE->BE connectivity + CORS verification ---------------------------------

def verify_connectivity_and_cors(backend_base: str, frontend_origin: str) -> tuple[str, list[str]]:
    """Confirm the backend answers a claim AND honors a cross-origin request from
    the frontend origin. Verification only — does not modify CORS config.

    Returns (verdict, evidence).
    """
    evidence = []
    # 1) direct claim call works against the dynamic backend port
    payload = json.dumps({"memberId": "M1", "drugId": "DRUG-001",
                          "quantity": 10, "submittedAmount": 1.0}).encode()
    req = urllib.request.Request(f"{backend_base}/api/claims", data=payload,
                                 headers={"Content-Type": "application/json",
                                          "Origin": frontend_origin})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read().decode())
            acao = r.headers.get("Access-Control-Allow-Origin")
            evidence.append(f"POST /api/claims from Origin {frontend_origin} -> HTTP {r.status}, status={body.get('status')}")
            evidence.append(f"Access-Control-Allow-Origin header: {acao!r}")
            if body.get("status") != "PAID":
                return "FAIL", evidence + ["unexpected adjudication for a valid claim"]
            if acao is None:
                return "FAIL", evidence + ["no CORS allow-origin header returned to the frontend origin"]
            return "PASS", evidence
    except urllib.error.HTTPError as e:
        return "FAIL", evidence + [f"HTTP error {e.code} verifying connectivity"]
    except (urllib.error.URLError, OSError) as e:
        return "BLOCKED", evidence + [f"could not reach backend for connectivity check: {e}"]


# --- main ---------------------------------------------------------------------

def _severity_exit(verdicts: list[str]) -> int:
    non_pass = {v for v in verdicts if v != "PASS"}
    if not non_pass:
        return 0
    sev = {"FAIL": 2, "BLOCKED": 3, "UNKNOWN": 4}
    return sev[max(non_pass, key=lambda v: sev.get(v, 0))]


# When True, the process exit code reflects the HISTORICAL recorded verdict
# instead of current application health. Set by the --historical-gate CLI flag.
gate_on_historical = False


def main() -> int:
    _install_signal_handlers()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)

    servers_meta: dict = {}
    conn_verdict, conn_evidence = "UNKNOWN", ["not run"]
    app_results = blocked_matrix("backend not started")
    app_meta = {"host": config.LOOPBACK, "port": None, "started": False,
                "python": _python_exe(), "note": "backend not started"}
    ui_result = None
    ui_meta = {}

    try:
        # --- 1-2. backend ---
        print("Starting fresh backend ...")
        be_proc, be_port, be_base, be_note = start_backend()
        be_ready = bool(be_proc) and be_note == ""
        servers_meta["backend"] = {
            "baseUrl": be_base or None, "port": be_port or None,
            "ready": be_ready, "pid": (be_proc.pid if be_proc else None),
            "note": be_note,
        }
        print(f"  backend ready={be_ready} at {be_base or '<none>'}")

        if be_ready:
            app_meta = {"host": config.LOOPBACK, "port": be_port, "started": True,
                        "python": _python_exe(), "note": ""}
            # --- 5. application matrix against the fresh backend ---
            app_results = run_matrix_against(be_base)

            # --- 3-4. frontend ---
            print("Starting fresh frontend (pointed at the isolated backend) ...")
            fe_proc, fe_port, fe_base, fe_note = start_frontend(be_base)
            fe_ready = bool(fe_proc) and fe_note == ""
            servers_meta["frontend"] = {
                "baseUrl": fe_base or None, "port": fe_port or None,
                "ready": fe_ready, "pid": (fe_proc.pid if fe_proc else None),
                "note": fe_note,
            }
            print(f"  frontend ready={fe_ready} at {fe_base or '<none>'}")

            if fe_ready:
                # --- connectivity + CORS verification ---
                conn_verdict, conn_evidence = verify_connectivity_and_cors(be_base, fe_base)
                print(f"  connectivity+CORS: {conn_verdict}")
                ui_meta = {"frontendBaseUrl": fe_base}
                # --- 6. Playwright UI tests ---
                print("Running Playwright UI tests against the fresh frontend ...")
                ui_result = run_ui_checks(fe_base)
                print(f"  UI verdict={ui_result.verdict} exit={ui_result.exit_code}")
            else:
                from ui_checks import UIResult
                ui_result = UIResult("BLOCKED", "frontend did not become ready",
                                     evidence=[fe_note or "frontend unavailable"])
                conn_verdict, conn_evidence = "BLOCKED", ["frontend not ready"]
        else:
            from ui_checks import UIResult
            ui_result = UIResult("BLOCKED", "backend did not become ready",
                                 evidence=[be_note or "backend unavailable"])
            conn_verdict, conn_evidence = "BLOCKED", ["backend not ready"]

        # --- 7. Kiro execution checks (unchanged) ---
        print("Evaluating recorded Kiro requirement-change turn ...")
        session_log = find_current_session_log(config.SESSIONS_DIR)
        turn = load_turn(session_log, config.TARGET_EXECUTION_ID, config.TARGET_PROMPT_PREFIX)
        kiro_results = run_all_kiro_checks(turn)

        # Fold connectivity/CORS into the Kiro-independent "application" evidence by
        # appending it as an extra application-style result row.
        from app_recheck import AppCheckResult
        app_results = list(app_results) + [
            AppCheckResult("FE->BE connectivity + CORS (dynamic ports)",
                           conn_verdict, "reachable + ACAO present",
                           "; ".join(conn_evidence)[:160])
        ]

        # --- 8. combined report (always produced) ---
        data = build_json(turn, app_results, app_meta, kiro_results,
                          ui_result=ui_result, ui_meta=ui_meta, servers_meta=servers_meta)
        json_path = os.path.join(out_dir, "evaluation.json")
        html_path = os.path.join(out_dir, "evaluation.html")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(build_html(data))

        # --- console summary ---
        print("\n=== CURRENT application validation (independently rerun) ===")
        for r in app_results:
            print(f"  [{r.verdict:7}] {r.label}")
        print(f"  [{ui_result.verdict:7}] UI / Playwright: {ui_result.summary} (actual exit={ui_result.exit_code})")
        print("\n=== HISTORICAL Kiro execution (recorded; informational) ===")
        for c in kiro_results:
            print(f"  [{c.verdict:7}] {c.title} — {c.summary}")

        current_verdict = data["currentApplicationValidation"]
        historical_verdict = data["historicalKiroExecution"]
        current_code = _severity_exit(
            [r.verdict for r in app_results] + [ui_result.verdict]
        )
        historical_code = _severity_exit([c.verdict for c in kiro_results])

        print(f"\nCurrent application validation: {current_verdict}")
        print(f"Historical Kiro execution:      {historical_verdict} "
              f"(informational; does not affect the default exit code)")
        print(f"Reports:\n  {json_path}\n  {html_path}")

        # Requirement: the PROCESS exit code reflects CURRENT application health.
        # A historical BLOCKED/FAIL/UNKNOWN stays visible but must NOT override it.
        # The separate historical gate is available explicitly via --historical-gate
        # (nonzero for historical FAIL/BLOCKED/UNKNOWN) for callers that want it.
        if gate_on_historical:
            print(f"[--historical-gate] exit code: {historical_code} "
                  f"(from historical verdict {historical_verdict})")
            return historical_code
        print(f"Exit code: {current_code} (from current application verdict {current_verdict})")
        return current_code
    finally:
        cleanup()


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Full current-vs-historical evaluation.")
    _ap.add_argument(
        "--historical-gate", action="store_true",
        help="Make the PROCESS exit code reflect the HISTORICAL recorded execution "
             "verdict (nonzero for FAIL/BLOCKED/UNKNOWN) instead of current app health. "
             "The report is identical either way; only the exit code changes.",
    )
    _args = _ap.parse_args()
    gate_on_historical = _args.historical_gate  # module-level global, read by main()
    raise SystemExit(main())
