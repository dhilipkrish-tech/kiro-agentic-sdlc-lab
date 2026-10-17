"""Render evaluation results to JSON and a self-contained HTML file.

Reports include only distilled evidence excerpts (short, relevant lines), never
raw session payloads.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from typing import Any

VERDICT_COLORS = {
    "PASS": "#1a7f37",
    "FAIL": "#cf222e",
    "BLOCKED": "#9a6700",
    "UNKNOWN": "#57606a",
}


def aggregate(verdicts: list[str]) -> str:
    """Aggregate a group of verdicts (worst-wins, missing != PASS)."""
    non_pass = {v for v in verdicts if v != "PASS"}
    if not non_pass:
        return "PASS"
    for sev in ("FAIL", "BLOCKED", "UNKNOWN"):
        if sev in non_pass:
            return sev
    return "UNKNOWN"


def current_application_verdict(app_results, ui_result) -> str:
    """Verdict for CURRENT application health: fresh backend + connectivity/CORS
    (both in app_results) plus the live Playwright UI rerun. Historical recorded
    execution is deliberately excluded."""
    verdicts = [r.verdict for r in app_results]
    if ui_result is not None:
        verdicts.append(ui_result.verdict)
    return aggregate(verdicts)


def historical_execution_verdict(kiro_results) -> str:
    """Verdict for the HISTORICAL recorded Kiro execution. Never forced to PASS;
    preserves BLOCKED/FAIL/UNKNOWN from the recorded evidence."""
    return aggregate([c.verdict for c in kiro_results])


def build_json(turn, app_results, app_meta, kiro_results,
               ui_result=None, ui_meta=None, servers_meta=None) -> dict[str, Any]:
    doc = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "currentApplicationValidation": current_application_verdict(app_results, ui_result),
        "historicalKiroExecution": historical_execution_verdict(kiro_results),
        "scope": {
            "sessionId": turn.session_id,
            "executionId": turn.execution_id,
            "promptExcerpt": turn.prompt_excerpt,
            "turnStart": turn.turn_start,
            "turnEnd": turn.turn_end,
            "note": "Evaluation restricted to the requirement-change turn only.",
        },
        "servers": servers_meta or {},
        "applicationChecks": {
            "method": "independently rerun against a fresh backend process",
            "backend": {
                "host": app_meta.get("host"),
                "port": app_meta.get("port"),
                "started": app_meta.get("started"),
                "python": app_meta.get("python"),
                "note": app_meta.get("note"),
            },
            "results": [
                {
                    "label": r.label,
                    "verdict": r.verdict,
                    "expected": r.expected,
                    "observed": r.observed,
                    "detail": r.detail,
                }
                for r in app_results
            ],
        },
        "kiroExecutionChecks": {
            "method": "derived from the recorded session log (Kiro-recorded)",
            "results": [
                {
                    "key": c.key,
                    "title": c.title,
                    "verdict": c.verdict,
                    "summary": c.summary,
                    "evidence": c.evidence,
                }
                for c in kiro_results
            ],
        },
    }
    if ui_result is not None:
        doc["uiChecks"] = {
            "method": "Playwright specs run against the fresh frontend (independently rerun)",
            "frontendBaseUrl": (ui_meta or {}).get("frontendBaseUrl"),
            "verdict": ui_result.verdict,
            "summary": ui_result.summary,
            "actualExitCode": ui_result.exit_code,
            "expectedTests": ui_result.expected_tests,
            "passed": ui_result.passed,
            "failed": ui_result.failed,
            "perTest": ui_result.per_test,
            "evidence": ui_result.evidence,
        }
    return doc


def _badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "#57606a")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:12px;font-weight:600">{html.escape(verdict)}</span>'
    )


def build_html(data: dict[str, Any]) -> str:
    scope = data["scope"]
    app = data["applicationChecks"]
    kiro = data["kiroExecutionChecks"]
    ui = data.get("uiChecks")
    servers = data.get("servers", {})
    current_verdict = data.get("currentApplicationValidation", "UNKNOWN")
    historical_verdict = data.get("historicalKiroExecution", "UNKNOWN")

    def ui_section() -> str:
        if not ui:
            return ""
        ev = "".join(f"<li><code>{html.escape(str(x))}</code></li>" for x in ui.get("evidence", []))
        return (
            '<h2>UI / Playwright checks <span class="tag">INDEPENDENTLY RERUN</span></h2>'
            f'<p class="muted">Method: {html.escape(ui["method"])}. '
            f'Frontend: <code>{html.escape(str(ui.get("frontendBaseUrl")))}</code>.</p>'
            '<div class="card">'
            f'<div class="card-head">Playwright UI tests {_badge(ui["verdict"])}</div>'
            f'<div class="muted">{html.escape(ui["summary"])} · '
            f'actual exit code: <code>{html.escape(str(ui.get("actualExitCode")))}</code> · '
            f'passed={html.escape(str(ui.get("passed")))} / expected={html.escape(str(ui.get("expectedTests")))}</div>'
            f'<ul class="evidence">{ev}</ul>'
            "</div>"
        )

    def servers_line() -> str:
        if not servers:
            return ""
        parts = []
        for name in ("backend", "frontend"):
            s = servers.get(name)
            if s:
                parts.append(
                    f"{name}: <code>{html.escape(str(s.get('baseUrl')))}</code> "
                    f"(ready={html.escape(str(s.get('ready')))}, pid={html.escape(str(s.get('pid')))})"
                )
        return "<p class='muted'>" + " · ".join(parts) + "</p>" if parts else ""

    def app_rows() -> str:
        out = []
        for r in app["results"]:
            out.append(
                "<tr>"
                f"<td>{html.escape(r['label'])}</td>"
                f"<td>{_badge(r['verdict'])}</td>"
                f"<td><code>{html.escape(r['expected'])}</code></td>"
                f"<td><code>{html.escape(r['observed'])}</code></td>"
                "</tr>"
            )
        return "\n".join(out)

    def kiro_blocks() -> str:
        out = []
        for c in kiro["results"]:
            ev = "".join(f"<li><code>{html.escape(x)}</code></li>" for x in c["evidence"])
            out.append(
                '<div class="card">'
                f'<div class="card-head">{html.escape(c["title"])} {_badge(c["verdict"])}</div>'
                f'<div class="muted">{html.escape(c["summary"])}</div>'
                f'<ul class="evidence">{ev}</ul>'
                "</div>"
            )
        return "\n".join(out)

    b = app["backend"]
    backend_line = (
        f"host {html.escape(str(b['host']))} · port {html.escape(str(b['port']))} · "
        f"started={html.escape(str(b['started']))}"
        + (f" · {html.escape(str(b['note']))}" if b.get("note") else "")
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluation — requirement-change turn</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem auto; max-width: 960px; color: #1f2328; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #d0d7de; padding-bottom: .3rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eaeef2; vertical-align: top; }}
  th {{ background: #f6f8fa; font-size: 13px; }}
  code {{ background: #f6f8fa; padding: 1px 5px; border-radius: 4px; font-size: 12px; }}
  .muted {{ color: #57606a; font-size: 13px; margin: .2rem 0 .4rem; }}
  .card {{ border: 1px solid #d0d7de; border-radius: 8px; padding: .8rem 1rem; margin: .7rem 0; }}
  .card-head {{ font-weight: 600; display: flex; gap: .6rem; align-items: center; }}
  .evidence {{ margin: .5rem 0 0; padding-left: 1.1rem; }}
  .evidence li {{ margin: 2px 0; font-size: 12px; line-height: 1.5; }}
  .scope {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; padding: .8rem 1rem; font-size: 13px; }}
  .tag {{ display:inline-block; background:#ddf4ff; color:#0969da; border-radius:6px; padding:1px 7px; font-size:11px; font-weight:600; }}
</style></head>
<body>
<h1>Automated Evaluation — requirement-change turn</h1>
<p class="muted">Generated {html.escape(data['generatedAt'])}</p>
<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin:.6rem 0">
  <div style="font-size:1.05rem">Current application validation: {_badge(current_verdict)}</div>
  <div style="font-size:1.05rem">Historical Kiro execution: {_badge(historical_verdict)}</div>
</div>
<p class="muted">These two verdicts are independent. The first reflects the live app
(fresh backend + connectivity/CORS + Playwright UI). The second preserves what the
original agent run recorded and never overrides current health.</p>
<div class="scope">
  <div><span class="tag">SCOPE</span> {html.escape(scope['note'])}</div>
  <div style="margin-top:.4rem">executionId: <code>{html.escape(scope['executionId'])}</code></div>
  <div>session: <code>{html.escape(scope['sessionId'])}</code></div>
  <div>turn: <code>{html.escape(str(scope['turnStart']))}</code> → <code>{html.escape(str(scope['turnEnd']))}</code></div>
  <div>prompt: <em>{html.escape(scope['promptExcerpt'])}</em></div>
  {servers_line()}
</div>

<h2>Application checks <span class="tag">INDEPENDENTLY RERUN</span></h2>
<p class="muted">Method: {html.escape(app['method'])}. Backend: {backend_line}.</p>
<table>
  <thead><tr><th>Check</th><th>Verdict</th><th>Expected</th><th>Observed</th></tr></thead>
  <tbody>
  {app_rows()}
  </tbody>
</table>

{ui_section()}

<h2>Kiro execution checks <span class="tag">KIRO-RECORDED</span></h2>
<p class="muted">Method: {html.escape(kiro['method'])}.</p>
{kiro_blocks()}

</body></html>
"""
