from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class CompletionUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_input_chars: int = 0
    estimated_output_chars: int = 0

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        estimated_input_chars: int,
        estimated_output_chars: int,
    ) -> "CompletionUsage":
        prompt = _usage_value(raw, "prompt_tokens")
        completion = _usage_value(raw, "completion_tokens")
        total = _usage_value(raw, "total_tokens")
        if total == 0 and prompt == 0 and completion == 0:
            prompt = _estimate_tokens_from_chars(estimated_input_chars)
            completion = _estimate_tokens_from_chars(estimated_output_chars)
            total = prompt + completion
        if total == 0 and (prompt or completion):
            total = prompt + completion
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            estimated_input_chars=estimated_input_chars,
            estimated_output_chars=estimated_output_chars,
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_input_chars": self.estimated_input_chars,
            "estimated_output_chars": self.estimated_output_chars,
        }


@dataclass(frozen=True)
class CompletionResult:
    content: str
    usage: CompletionUsage

    def __str__(self) -> str:
        return self.content

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.content == other
        if isinstance(other, CompletionResult):
            return self.content == other.content and self.usage == other.usage
        return NotImplemented


class UsageLedger:
    def __init__(self, path: Optional[Path] = None):
        configured = os.getenv("CODEX_DEEP_LOOP_MCP_USAGE_LEDGER") or os.getenv(
            "CODEX_RWTH_MCP_USAGE_LEDGER"
        )
        self._path = (
            path
            or (Path(configured).expanduser() if configured else None)
            or Path.home() / ".cache" / "codex-deep-loop-mcp" / "usage.jsonl"
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Dict[str, Any]) -> None:
        safe = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": event.get("tool_name", ""),
            "phase": event.get("phase", ""),
            "role": event.get("role", ""),
            "analysis_depth": event.get("analysis_depth", ""),
            "model_id": event.get("model_id", ""),
            "cache_hit": bool(event.get("cache_hit", False)),
            "cache_saved_call": bool(event.get("cache_saved_call", False)),
            "prompt_tokens": int(event.get("prompt_tokens", 0)),
            "completion_tokens": int(event.get("completion_tokens", 0)),
            "total_tokens": int(event.get("total_tokens", 0)),
            "estimated_input_chars": int(event.get("estimated_input_chars", 0)),
            "estimated_output_chars": int(event.get("estimated_output_chars", 0)),
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, sort_keys=True) + "\n")

    def report(self, *, days: int = 7, group_by: str = "tool") -> Dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 0))
        events = [event for event in self._read_events() if _event_time(event) >= cutoff]
        group_field = "model_id" if group_by == "model" else "tool_name"
        groups: Dict[str, Dict[str, Any]] = {}
        totals = _empty_totals()
        for event in events:
            _add_event(totals, event)
            group = groups.setdefault(str(event.get(group_field, "")), _empty_totals())
            _add_event(group, event)
        return {
            "days": days,
            "group_by": group_by,
            "ledger_path": str(self._path),
            "totals": totals,
            "groups": groups,
        }

    def _read_events(self) -> Iterable[Dict[str, Any]]:
        if not self._path.exists():
            return []
        events = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


def _usage_value(raw: Any, key: str) -> int:
    if raw is None:
        return 0
    if isinstance(raw, dict):
        value = raw.get(key, 0)
    else:
        value = getattr(raw, key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _estimate_tokens_from_chars(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, round(chars / 4))


def _empty_totals() -> Dict[str, Any]:
    return {
        "calls": 0,
        "cache_hits": 0,
        "cache_saved_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_input_chars": 0,
        "estimated_output_chars": 0,
        "model_ids": [],
        "roles": [],
        "analysis_depths": [],
    }


def _add_event(target: Dict[str, Any], event: Dict[str, Any]) -> None:
    if not event.get("cache_hit"):
        target["calls"] += 1
    if event.get("cache_hit"):
        target["cache_hits"] += 1
    if event.get("cache_saved_call"):
        target["cache_saved_calls"] += 1
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_input_chars",
        "estimated_output_chars",
    ):
        target[key] += int(event.get(key, 0))
    model_id = event.get("model_id")
    if model_id and model_id not in target["model_ids"]:
        target["model_ids"].append(model_id)
    role = event.get("role")
    if role and role not in target["roles"]:
        target["roles"].append(role)
    analysis_depth = event.get("analysis_depth")
    if analysis_depth and analysis_depth not in target["analysis_depths"]:
        target["analysis_depths"].append(analysis_depth)


def _event_time(event: Dict[str, Any]) -> datetime:
    raw = str(event.get("timestamp", ""))
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
