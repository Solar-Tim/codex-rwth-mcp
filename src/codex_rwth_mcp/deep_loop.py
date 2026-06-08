from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import AppConfig
from .prompts import SYSTEM_PROMPT
from .router import ModelRouter
from .rwth_client import RwthClient

PROMPT_VERSION = "deep-loop-v1"
MAX_DEEP_LOOP_CALLS = 8
DEFAULT_CHUNK_CHARS = 12_000
DEFAULT_DIFF_CHUNK_LINES = 100
DEFAULT_MAX_FILE_BYTES = 128_000


@dataclass(frozen=True)
class FileEvidence:
    text: str
    safety_notes: List[str]


class FileEvidenceLoader:
    def __init__(
        self,
        repo_root: Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ):
        self._repo_root = repo_root.resolve()
        self._max_file_bytes = max_file_bytes

    def load(self, file_paths: Sequence[str]) -> FileEvidence:
        chunks: List[str] = []
        safety_notes: List[str] = []
        for raw_path in file_paths:
            if not raw_path:
                continue
            try:
                resolved = (self._repo_root / raw_path).resolve()
            except OSError as exc:
                safety_notes.append(f"skipped {raw_path}: could not resolve path ({exc})")
                continue

            reason = self._blocked_reason(resolved)
            if reason:
                safety_notes.append(f"skipped {raw_path}: {reason}")
                continue

            try:
                size = resolved.stat().st_size
            except OSError as exc:
                safety_notes.append(f"skipped {raw_path}: could not stat file ({exc})")
                continue
            if size > self._max_file_bytes:
                safety_notes.append(
                    f"skipped {raw_path}: file exceeds {self._max_file_bytes} byte limit"
                )
                continue

            try:
                data = resolved.read_bytes()
            except OSError as exc:
                safety_notes.append(f"skipped {raw_path}: could not read file ({exc})")
                continue
            if _looks_binary(data):
                safety_notes.append(f"skipped {raw_path}: binary file")
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                safety_notes.append(f"skipped {raw_path}: not valid UTF-8 text")
                continue

            display_path = resolved.relative_to(self._repo_root).as_posix()
            chunks.append(f"--- {display_path} ---\n{text}")

        return FileEvidence(text="\n\n".join(chunks), safety_notes=safety_notes)

    def _blocked_reason(self, resolved: Path) -> str:
        if not _is_relative_to(resolved, self._repo_root):
            return "path escapes repo root"
        relative = resolved.relative_to(self._repo_root)
        parts = set(relative.parts)
        name = relative.name
        normalized = relative.as_posix()
        if ".git" in parts:
            return ".git paths are blocked"
        if ".venv" in parts or "venv" in parts:
            return "virtual environment paths are blocked"
        if name == ".env" or name.startswith(".env."):
            return "environment files are blocked"
        if name.endswith(".key") or name.endswith(".pem"):
            return "key material is blocked"
        if normalized == "config/routing.local.yaml":
            return "local routing config is blocked"
        return ""


class JsonResponseCache:
    def __init__(self, cache_dir: Optional[Path] = None):
        configured = os.getenv("CODEX_RWTH_MCP_CACHE_DIR")
        self._cache_dir = (
            cache_dir
            or (Path(configured).expanduser() if configured else None)
            or Path.home() / ".cache" / "codex-rwth-mcp"
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Optional[str]:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        content = payload.get("content")
        return content if isinstance(content, str) else None

    def set(self, key: str, content: str) -> None:
        self._path_for(key).write_text(
            json.dumps({"content": content}),
            encoding="utf-8",
        )

    def make_key(
        self,
        *,
        tool_name: str,
        phase: str,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        payload = {
            "prompt_version": PROMPT_VERSION,
            "tool_name": tool_name,
            "phase": phase,
            "model_id": model_id,
            "system_prompt_sha256": _sha256(system_prompt),
            "user_prompt_sha256": _sha256(user_prompt),
        }
        return _sha256(json.dumps(payload, sort_keys=True))

    def _path_for(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"


class DeepLoopService:
    def __init__(
        self,
        *,
        config: AppConfig,
        router: ModelRouter,
        client: RwthClient,
        repo_root: Optional[Path] = None,
        cache: Optional[JsonResponseCache] = None,
        max_calls: int = MAX_DEEP_LOOP_CALLS,
    ):
        self._config = config
        self._router = router
        self._client = client
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._cache = cache or JsonResponseCache()
        self._max_calls = max_calls
        from .deep_loop_graph import DeepLoopGraphRunner

        self._graph_runner = DeepLoopGraphRunner(self)
        self._reset_metrics()

    async def deep_debug_loop(
        self,
        *,
        logs: str,
        context: str = "",
        failing_command: str = "",
        file_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        return await self._graph_runner.deep_debug_loop(
            logs=logs,
            context=context,
            failing_command=failing_command,
            file_paths=file_paths,
        )

    async def deep_diff_review(
        self,
        *,
        diff: str = "",
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        return await self._graph_runner.deep_diff_review(
            diff=diff,
            context=context,
            file_paths=file_paths,
        )

    async def repo_map_loop(
        self,
        *,
        question: str,
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        self._reset_metrics()
        return await self._graph_runner.repo_map_loop(
            question=question,
            file_paths=file_paths,
            file_tree=file_tree,
            context=context,
        )

    async def _complete_text(self, *, tool_name: str, phase: str, user_prompt: str) -> str:
        self._ensure_call_budget()
        decision = self._router.route(
            tool_name=tool_name,
            input_chars=len(user_prompt),
            needs_vision=False,
        )
        self._model_ids.add(decision.model.id)
        key = self._cache.make_key(
            tool_name=tool_name,
            phase=phase,
            model_id=decision.model.id,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        cached = self._cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            return cached

        tool_config = self._config.tools[tool_name]
        self._calls_used += 1
        content = await self._client.complete_text(
            model=decision.model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=tool_config.max_output_tokens,
            temperature=tool_config.temperature,
        )
        self._cache.set(key, content)
        return content

    def _ensure_call_budget(self) -> None:
        if self._calls_used >= self._max_calls:
            raise RuntimeError(f"deep loop exceeded {self._max_calls} model calls")

    def _result_from_text(
        self,
        tool_name: str,
        text: str,
        safety_notes: Sequence[str],
    ) -> Dict[str, Any]:
        parsed = _parse_handoff(text)
        status = parsed["status"]
        if status == "complete" and parsed["requested_evidence"]:
            status = "needs_codex_input"
        if status == "needs_codex_input" and not parsed["next_codex_actions"]:
            parsed["next_codex_actions"].append(
                "Gather requested evidence and call this tool again."
            )
        return {
            "tool": tool_name,
            "status": status,
            "summary": parsed["summary"] or text,
            "findings": parsed["findings"],
            "risks": parsed["risks"],
            "requested_evidence": parsed["requested_evidence"],
            "next_codex_actions": parsed["next_codex_actions"],
            "calls_used": self._calls_used,
            "cache_hits": self._cache_hits,
            "model_ids": sorted(self._model_ids),
            "safety_notes": list(safety_notes),
        }

    def _reset_metrics(self) -> None:
        self._calls_used = 0
        self._cache_hits = 0
        self._model_ids: set[str] = set()


def _chunk_text(text: str, *, max_chars: int = DEFAULT_CHUNK_CHARS) -> List[str]:
    if not text:
        return [""]
    return [text[start : start + max_chars] for start in range(0, len(text), max_chars)]


def _chunk_diff(text: str, *, max_lines: int = DEFAULT_DIFF_CHUNK_LINES) -> List[str]:
    lines = text.splitlines()
    if not lines:
        return [""]
    return [
        "\n".join(lines[start : start + max_lines])
        for start in range(0, len(lines), max_lines)
    ]


def _parse_handoff(text: str) -> Dict[str, Any]:
    parsed = {
        "status": "complete",
        "summary": "",
        "findings": [],
        "risks": [],
        "requested_evidence": [],
        "next_codex_actions": [],
    }
    lowered = text.lower()
    if "needs_codex_input" in lowered:
        parsed["status"] = "needs_codex_input"
    elif "blocked" in lowered:
        parsed["status"] = "blocked"

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if not value:
            continue
        if key == "status" and value in {"complete", "needs_codex_input", "blocked"}:
            parsed["status"] = value
        elif key == "summary":
            parsed["summary"] = value
        elif key in {"finding", "findings"}:
            parsed["findings"].append(value)
        elif key in {"risk", "risks"}:
            parsed["risks"].append(value)
        elif key in {"requested_evidence", "request"}:
            parsed["requested_evidence"].append(value)
        elif key in {"next_codex_action", "next_codex_actions", "next_action"}:
            parsed["next_codex_actions"].append(value)

    if not parsed["summary"]:
        parsed["summary"] = text.strip()
    if parsed["status"] == "needs_codex_input" and not parsed["requested_evidence"]:
        parsed["requested_evidence"].append(text.strip())
    if not parsed["findings"] and parsed["summary"]:
        parsed["findings"].append(parsed["summary"])
    return parsed


def _join_evidence(parts: Iterable[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:2048] or data.startswith(b"\x89PNG")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
