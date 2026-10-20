"""Read-only reader for a single Kiro session log, scoped to one turn.

This module ONLY reads ``messages.jsonl``. It never writes, and it never emits
raw session content to callers beyond the small, relevant fields the checks need
(tool name, action type, selected argument values, success flag, short result
excerpts, timestamps). Full raw payloads are deliberately not surfaced.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolEvent:
    """A recorded tool_call paired with its tool_result (if any)."""

    index: int
    tool_name: str
    action_type: Optional[str]
    tool_call_id: Optional[str]
    args: dict[str, Any]
    call_timestamp: Optional[str]
    success: Optional[bool] = None
    result_excerpt: Optional[str] = None
    result_timestamp: Optional[str] = None
    # Larger (still bounded) head+tail capture, retained only for shell/test
    # commands so numeric summaries (e.g. pytest's "N passed") remain verifiable.
    # Not emitted verbatim into reports.
    result_summary: Optional[str] = None


@dataclass
class TurnData:
    """Everything the checks need about the selected turn."""

    execution_id: str
    session_id: str
    session_path: str
    prompt_excerpt: str
    turn_start: Optional[str]
    turn_end: Optional[str]
    tool_events: list[ToolEvent] = field(default_factory=list)
    usage_elapsed_ms: Optional[int] = None
    report_text: str = ""


def find_current_session_log(sessions_dir: str) -> str:
    """Return the most-recently-modified messages.jsonl under ``sessions_dir``.

    The target turn lives in the active session; selecting by mtime keeps the
    harness from hardcoding a session id.
    """
    candidates = glob.glob(os.path.join(sessions_dir, "*", "messages.jsonl"))
    if not candidates:
        raise FileNotFoundError(f"No session logs found under {sessions_dir}")
    return max(candidates, key=os.path.getmtime)


def _excerpt(value: Any, limit: int = 240) -> str:
    """Collapse a value to a single short line; never dump whole payloads."""
    if value is None:
        return ""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit] + " …"


def _head_tail(value: Any, head: int = 600, tail: int = 600) -> str:
    """Bounded head+tail of a value, so trailing summaries (e.g. a test count
    line printed last) survive. Still never the full raw payload for large output.
    """
    if value is None:
        return ""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    if len(s) <= head + tail + 20:
        return s
    return s[:head] + " … " + s[-tail:]


def load_turn(session_path: str, execution_id: str, prompt_prefix: str) -> TurnData:
    """Parse ``session_path`` and extract only events for ``execution_id``.

    The user prompt that opened the turn is captured separately (user messages do
    not always carry the executionId) by taking the last user message seen before
    the turn's ``turn_start``.
    """
    session_id = os.path.basename(os.path.dirname(session_path))

    turn_start = turn_end = None
    usage_ms: Optional[int] = None
    prompt_excerpt = ""
    last_user_before = ""

    calls: dict[str, ToolEvent] = {}
    results: dict[str, tuple[Optional[bool], str, Optional[str], str]] = {}
    order: list[str] = []
    report_chunks: list[str] = []
    seen_turn_start = False

    with open(session_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload", {})
            if not isinstance(payload, dict):
                continue
            ptype = payload.get("type")
            ts = obj.get("timestamp")

            # Track the most recent user prompt so we can attribute it to the turn.
            if ptype == "user" and not seen_turn_start:
                content = payload.get("content")
                last_user_before = content if isinstance(content, str) else _excerpt(content, 400)

            if payload.get("executionId") != execution_id:
                continue

            if ptype == "turn_start":
                seen_turn_start = True
                turn_start = ts
                if last_user_before.startswith(prompt_prefix):
                    prompt_excerpt = _excerpt(last_user_before, 160)
                else:
                    prompt_excerpt = _excerpt(last_user_before, 160)
            elif ptype == "turn_end":
                turn_end = ts
            elif ptype == "usage_summary":
                et = payload.get("elapsedTime")
                if isinstance(et, (int, float)):
                    usage_ms = int(et)
            elif ptype == "tool_call":
                cid = payload.get("toolCallId")
                order.append(cid)
                calls[cid] = ToolEvent(
                    index=len(order),
                    tool_name=payload.get("toolName", "<unknown>"),
                    action_type=payload.get("actionType"),
                    tool_call_id=cid,
                    args=payload.get("args") if isinstance(payload.get("args"), dict) else {},
                    call_timestamp=ts,
                )
            elif ptype == "tool_result":
                cid = payload.get("toolCallId")
                content = payload.get("content")
                results[cid] = (
                    payload.get("success"),
                    _excerpt(content),
                    ts,
                    _head_tail(content),
                )
            elif ptype == "assistant":
                content = payload.get("content")
                if isinstance(content, str):
                    report_chunks.append(content)
                elif isinstance(content, list):
                    for seg in content:
                        if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                            report_chunks.append(seg["text"])
                        elif isinstance(seg, str):
                            report_chunks.append(seg)

    tool_events: list[ToolEvent] = []
    for cid in order:
        ev = calls[cid]
        if cid in results:
            succ, excerpt, rts, summary = results[cid]
            ev.success = succ
            ev.result_excerpt = excerpt
            ev.result_timestamp = rts
            ev.result_summary = summary
        tool_events.append(ev)

    return TurnData(
        execution_id=execution_id,
        session_id=session_id,
        session_path=session_path,
        prompt_excerpt=prompt_excerpt,
        turn_start=turn_start,
        turn_end=turn_end,
        tool_events=tool_events,
        usage_elapsed_ms=usage_ms,
        report_text="".join(report_chunks),
    )
