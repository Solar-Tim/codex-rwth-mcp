from __future__ import annotations

import hashlib
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import AppConfig
from .prompts import SYSTEM_PROMPT
from .router import ModelRouter
from .rwth_client import RwthClient
from .usage import CompletionResult, CompletionUsage, UsageLedger

PROMPT_VERSION = "deep-loop-v1"
MAX_DEEP_LOOP_CALLS = 8
MAX_CONCURRENT_MODEL_CALLS = 2
DEFAULT_ANALYSIS_DEPTH = "deep"
ANALYSIS_DEPTH_BUDGETS = {
    "fast": 4,
    "standard": 8,
    "deep": 16,
    "exhaustive": 32,
}
DEFAULT_CHUNK_CHARS = 12_000
DEFAULT_DIFF_CHUNK_LINES = 100
DEFAULT_MAX_FILE_BYTES = 128_000
EXTERNAL_SCAN_MAX_FILES = 80
EXTERNAL_SCAN_MAX_TREE_LINES = 500


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
        usage_ledger: Optional[UsageLedger] = None,
        max_calls: int = MAX_DEEP_LOOP_CALLS,
    ):
        self._config = config
        self._router = router
        self._client = client
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._cache = cache or JsonResponseCache()
        self._usage_ledger = usage_ledger or UsageLedger()
        self._max_calls = max_calls
        self._model_call_semaphore = asyncio.Semaphore(MAX_CONCURRENT_MODEL_CALLS)
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
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("deep_debug_loop", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("deep_debug_loop", repo_root):
            return blocked
        return await self._graph_runner.deep_debug_loop(
            logs=logs,
            context=context,
            failing_command=failing_command,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def deep_diff_review(
        self,
        *,
        diff: str = "",
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("deep_diff_review", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("deep_diff_review", repo_root):
            return blocked
        return await self._graph_runner.deep_diff_review(
            diff=diff,
            context=context,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def repo_map_loop(
        self,
        *,
        question: str,
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        context: str = "",
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("repo_map_loop", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("repo_map_loop", repo_root):
            return blocked
        return await self._graph_runner.repo_map_loop(
            question=question,
            file_paths=file_paths,
            file_tree=file_tree,
            context=context,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def deep_repo_review_loop(
        self,
        *,
        question: str,
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        context: str = "",
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("deep_repo_review_loop", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("deep_repo_review_loop", repo_root):
            return blocked
        return await self._graph_runner.generic_repo_loop(
            tool_name="deep_repo_review_loop",
            question=question,
            file_paths=file_paths,
            file_tree=file_tree,
            context=context,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def deep_test_strategy_loop(
        self,
        *,
        diff: str = "",
        failing_tests: str = "",
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("deep_test_strategy_loop", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("deep_test_strategy_loop", repo_root):
            return blocked
        question = "Create a focused test strategy for this change."
        combined_context = _join_evidence([context, failing_tests, diff])
        return await self._graph_runner.generic_repo_loop(
            tool_name="deep_test_strategy_loop",
            question=question,
            file_paths=file_paths,
            file_tree="",
            context=combined_context,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def deep_architecture_critic(
        self,
        *,
        question: str,
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
        repo_root: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("deep_architecture_critic", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("deep_architecture_critic", repo_root):
            return blocked
        return await self._graph_runner.generic_repo_loop(
            tool_name="deep_architecture_critic",
            question=question,
            file_paths=file_paths,
            file_tree="",
            context=context,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    async def coding_task_loop(
        self,
        *,
        task: str,
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        repo_root: str = "",
        constraints: str = "",
        test_command: str = "",
        analysis_depth: str = DEFAULT_ANALYSIS_DEPTH,
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if blocked := self._configure_analysis_depth("coding_task_loop", analysis_depth):
            return blocked
        if blocked := self._blocked_repo_root_result("coding_task_loop", repo_root):
            return blocked
        if _looks_unsafe_task(_join_evidence([task, context, constraints, test_command])):
            return self._blocked_result(
                "coding_task_loop",
                ["task appears to require secrets, live infrastructure mutation, or uncontrolled execution"],
            )
        return await self._graph_runner.coding_task_loop(
            task=task,
            context=context,
            file_paths=file_paths,
            file_tree=file_tree,
            repo_root=repo_root,
            constraints=constraints,
            test_command=test_command,
            analysis_depth=analysis_depth,
        )

    async def external_repo_scan_loop(
        self,
        *,
        repo_url: str,
        question: str,
        ref: str = "main",
    ) -> Dict[str, Any]:
        self._reset_metrics()
        if not repo_url.startswith(("https://github.com/", "git@github.com:")):
            return self._blocked_result(
                "external_repo_scan_loop",
                ["only GitHub repository URLs are allowed for external scans"],
            )
        try:
            file_tree, file_evidence, safety_notes = self._prepare_external_repo_scan(
                repo_url=repo_url,
                ref=ref,
            )
        except RuntimeError as exc:
            return self._blocked_result("external_repo_scan_loop", [str(exc)])
        context = _join_evidence(
            [
                f"Read-only external repo scan for {repo_url} at ref {ref}. Do not execute code.",
                file_evidence,
            ]
        )
        result = await self._graph_runner.generic_repo_loop(
            tool_name="external_repo_scan_loop",
            question=question,
            file_paths=[],
            file_tree=file_tree,
            context=context,
            repo_root="",
            analysis_depth=DEFAULT_ANALYSIS_DEPTH,
        )
        result["safety_notes"] = list(result.get("safety_notes", [])) + safety_notes
        return result

    def _prepare_external_repo_scan(self, *, repo_url: str, ref: str) -> tuple[str, str, List[str]]:
        external_root = self._cache._cache_dir / "external-repos"
        external_root.mkdir(parents=True, exist_ok=True)
        repo_dir = external_root / _sha256(f"{repo_url}@{ref}")[:16]
        if repo_dir.exists():
            _run_git(["git", "-C", str(repo_dir), "fetch", "--depth=1", "origin", ref])
            _run_git(["git", "-C", str(repo_dir), "checkout", "--detach", "FETCH_HEAD"])
        else:
            _run_git(["git", "clone", "--depth=1", "--branch", ref, repo_url, str(repo_dir)])

        selected_paths: List[str] = []
        tree_lines: List[str] = []
        for path in sorted(repo_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(repo_dir).as_posix()
            if len(tree_lines) < EXTERNAL_SCAN_MAX_TREE_LINES:
                tree_lines.append(relative)
            if len(selected_paths) >= EXTERNAL_SCAN_MAX_FILES:
                continue
            if _is_external_scan_candidate(path):
                selected_paths.append(relative)

        evidence = FileEvidenceLoader(repo_dir).load(selected_paths)
        safety_notes = [
            f"external repo cloned read-only into cache: {repo_dir}",
            f"external scan selected {len(selected_paths)} safe text candidate files",
        ] + evidence.safety_notes
        return "\n".join(tree_lines), evidence.text, safety_notes

    def usage_report(self, *, days: int = 7, group_by: str = "tool") -> Dict[str, Any]:
        return self._usage_ledger.report(days=days, group_by=group_by)

    async def _complete_text(
        self,
        *,
        tool_name: str,
        phase: str,
        user_prompt: str,
        role: str = "",
    ) -> str:
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
            usage = CompletionUsage.from_raw(
                None,
                estimated_input_chars=len(user_prompt),
                estimated_output_chars=len(cached),
            )
            self._record_usage(
                tool_name=tool_name,
                phase=phase,
                model_id=decision.model.id,
                usage=usage,
                cache_hit=True,
                role=role,
            )
            return cached

        tool_config = self._config.tools[tool_name]
        async with self._model_call_semaphore:
            self._calls_used += 1
            completion = _as_completion(
                await self._client.complete_text(
                    model=decision.model,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_output_tokens=tool_config.max_output_tokens,
                    temperature=tool_config.temperature,
                ),
                estimated_input_chars=len(SYSTEM_PROMPT) + len(user_prompt),
            )
        content = completion.content
        self._record_usage(
            tool_name=tool_name,
            phase=phase,
            model_id=decision.model.id,
            usage=completion.usage,
            cache_hit=False,
            role=role,
        )
        self._cache.set(key, content)
        return content

    def _ensure_call_budget(self) -> None:
        if self._calls_used >= self._active_max_calls:
            raise RuntimeError(f"deep loop exceeded {self._active_max_calls} model calls")

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
            "implementation_plan": parsed["implementation_plan"],
            "patch_draft": parsed["patch_draft"],
            "files_changed": parsed["files_changed"],
            "tests_to_run": parsed["tests_to_run"],
            "ranked_findings": parsed["ranked_findings"],
            "evidence_references": parsed["evidence_references"],
            "disagreements": parsed["disagreements"],
            "confidence": parsed["confidence"],
            "verification_hints": parsed["verification_hints"],
            "analysis_depth": self._analysis_depth,
            "roles_used": list(self._roles_used),
            "calls_used": self._calls_used,
            "cache_hits": self._cache_hits,
            "model_ids": sorted(self._model_ids),
            **self._usage_totals(),
            "usage_by_phase": list(self._usage_by_phase),
            "safety_notes": list(safety_notes),
        }

    def _reset_metrics(self) -> None:
        self._calls_used = 0
        self._cache_hits = 0
        self._model_ids: set[str] = set()
        self._usage_by_phase: List[Dict[str, Any]] = []
        self._analysis_depth = DEFAULT_ANALYSIS_DEPTH
        self._active_max_calls = ANALYSIS_DEPTH_BUDGETS[DEFAULT_ANALYSIS_DEPTH]
        self._roles_used: List[str] = []

    def _record_usage(
        self,
        *,
        tool_name: str,
        phase: str,
        model_id: str,
        usage: CompletionUsage,
        cache_hit: bool,
        role: str = "",
    ) -> None:
        event = {
            "tool_name": tool_name,
            "phase": phase,
            "role": role or _role_from_phase(phase),
            "analysis_depth": self._analysis_depth,
            "model_id": model_id,
            "cache_hit": cache_hit,
            "cache_saved_call": cache_hit,
            **usage.to_dict(),
        }
        self._usage_by_phase.append(event)
        self._usage_ledger.append(event)

    def _configure_analysis_depth(self, tool_name: str, analysis_depth: str) -> Optional[Dict[str, Any]]:
        if analysis_depth not in ANALYSIS_DEPTH_BUDGETS:
            return self._blocked_result(
                tool_name,
                [
                    f"invalid analysis_depth {analysis_depth!r}; use one of fast, standard, deep, exhaustive"
                ],
            )
        self._analysis_depth = analysis_depth
        self._active_max_calls = ANALYSIS_DEPTH_BUDGETS[analysis_depth]
        return None

    def _set_roles_used(self, roles: Sequence[str]) -> None:
        self._roles_used = list(dict.fromkeys(roles))

    def _usage_totals(self) -> Dict[str, int]:
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_input_chars": 0,
            "estimated_output_chars": 0,
        }
        for event in self._usage_by_phase:
            for key in totals:
                totals[key] += int(event.get(key, 0))
        return totals

    def _resolve_repo_root(self, repo_root: str = "") -> Path:
        if not repo_root:
            return self._repo_root
        configured = self._config.repo_roots.get(repo_root)
        if configured is None:
            raise ValueError(f"unknown repo_root {repo_root!r}; use a configured repo_roots name")
        return configured.resolve()

    def _blocked_repo_root_result(self, tool_name: str, repo_root: str) -> Optional[Dict[str, Any]]:
        if not repo_root:
            return None
        try:
            self._resolve_repo_root(repo_root)
        except ValueError as exc:
            return self._blocked_result(tool_name, [str(exc)])
        return None

    def _blocked_result(self, tool_name: str, safety_notes: Sequence[str]) -> Dict[str, Any]:
        return {
            "tool": tool_name,
            "status": "blocked",
            "summary": "; ".join(safety_notes),
            "findings": [],
            "risks": [],
            "requested_evidence": [],
            "next_codex_actions": [],
            "implementation_plan": "",
            "patch_draft": "",
            "files_changed": [],
            "tests_to_run": [],
            "ranked_findings": [],
            "evidence_references": [],
            "disagreements": [],
            "confidence": "",
            "verification_hints": [],
            "analysis_depth": self._analysis_depth,
            "roles_used": list(self._roles_used),
            "calls_used": self._calls_used,
            "cache_hits": self._cache_hits,
            "model_ids": sorted(self._model_ids),
            **self._usage_totals(),
            "usage_by_phase": list(self._usage_by_phase),
            "safety_notes": list(safety_notes),
        }


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
        "implementation_plan": "",
        "patch_draft": "",
        "files_changed": [],
        "tests_to_run": [],
        "ranked_findings": [],
        "evidence_references": [],
        "disagreements": [],
        "confidence": "",
        "verification_hints": [],
    }
    lowered = text.lower()
    if "needs_codex_input" in lowered:
        parsed["status"] = "needs_codex_input"
    elif "blocked" in lowered:
        parsed["status"] = "blocked"

    current_section = ""
    list_sections = {
        "finding",
        "findings",
        "risk",
        "risks",
        "requested_evidence",
        "request",
        "next_codex_action",
        "next_codex_actions",
        "next_action",
        "files_changed",
        "file_changed",
        "tests_to_run",
        "test_to_run",
        "ranked_finding",
        "ranked_findings",
        "evidence_reference",
        "evidence_references",
        "disagreement",
        "disagreements",
        "verification_hint",
        "verification_hints",
    }
    scalar_sections = {"patch_draft"}
    known_sections = list_sections | scalar_sections | {
        "status",
        "summary",
        "implementation_plan",
    }
    patch_draft_lines: List[str] = []

    for raw_line in text.splitlines():
        raw_stripped = raw_line.strip()
        bullet_value = ""
        if raw_stripped.startswith(("-", "*")):
            bullet_value = raw_stripped[1:].strip()
        line = raw_stripped.lstrip("-* ").strip()
        if current_section == "patch_draft":
            maybe_key = ""
            if ":" in line:
                maybe_key = line.split(":", 1)[0].strip().lower().replace(" ", "_")
            if maybe_key not in known_sections:
                patch_draft_lines.append(raw_line)
                continue
        if not line or ":" not in line:
            if current_section == "patch_draft":
                patch_draft_lines.append(raw_line)
                continue
            if bullet_value and current_section in {"requested_evidence", "request"}:
                if not _is_empty_evidence_value(bullet_value):
                    parsed["requested_evidence"].append(bullet_value)
            elif bullet_value and current_section in {"finding", "findings"}:
                parsed["findings"].append(bullet_value)
            elif bullet_value and current_section in {"risk", "risks"}:
                parsed["risks"].append(bullet_value)
            elif bullet_value and current_section in {
                "next_codex_action",
                "next_codex_actions",
                "next_action",
            }:
                parsed["next_codex_actions"].append(bullet_value)
            elif bullet_value and current_section in {"ranked_finding", "ranked_findings"}:
                parsed["ranked_findings"].append(bullet_value)
            elif bullet_value and current_section in {"evidence_reference", "evidence_references"}:
                parsed["evidence_references"].append(bullet_value)
            elif bullet_value and current_section in {"disagreement", "disagreements"}:
                parsed["disagreements"].append(bullet_value)
            elif bullet_value and current_section in {"verification_hint", "verification_hints"}:
                parsed["verification_hints"].append(bullet_value)
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        current_section = key if key in list_sections | scalar_sections else ""
        clean_value = _clean_markdown_scalar(value)
        if not value:
            continue
        if key == "status" and clean_value in {"complete", "needs_codex_input", "blocked"}:
            parsed["status"] = clean_value
        elif key == "summary":
            summary_value = _clean_summary_scalar(clean_value)
            if summary_value and not parsed["summary"]:
                parsed["summary"] = summary_value
        elif key in {"finding", "findings"}:
            if clean_value:
                parsed["findings"].append(clean_value)
        elif key in {"risk", "risks"}:
            if clean_value:
                parsed["risks"].append(clean_value)
        elif key in {"requested_evidence", "request"}:
            if clean_value and not _is_empty_evidence_value(clean_value):
                parsed["requested_evidence"].append(clean_value)
        elif key in {"next_codex_action", "next_codex_actions", "next_action"}:
            if clean_value:
                parsed["next_codex_actions"].append(clean_value)
        elif key == "implementation_plan":
            if clean_value:
                parsed["implementation_plan"] = clean_value
        elif key == "patch_draft":
            if value and value != "|":
                patch_draft_lines.append(value)
        elif key in {"files_changed", "file_changed"}:
            parsed["files_changed"].extend(_split_list_value(value))
        elif key in {"tests_to_run", "test_to_run"}:
            parsed["tests_to_run"].extend(_split_list_value(value))
        elif key in {"ranked_finding", "ranked_findings"}:
            if clean_value:
                parsed["ranked_findings"].append(clean_value)
        elif key in {"evidence_reference", "evidence_references"}:
            parsed["evidence_references"].extend(_split_list_value(clean_value))
        elif key in {"disagreement", "disagreements"}:
            if clean_value and not _is_empty_structured_list_value(clean_value):
                parsed["disagreements"].append(clean_value)
        elif key == "confidence":
            if clean_value:
                parsed["confidence"] = clean_value
        elif key in {"verification_hint", "verification_hints"}:
            if clean_value:
                parsed["verification_hints"].append(clean_value)

    if patch_draft_lines:
        parsed["patch_draft"] = _clean_patch_draft("\n".join(patch_draft_lines))
    if not parsed["summary"]:
        parsed["summary"] = _clean_summary_scalar(text.strip())
    parsed["requested_evidence"] = _dedupe_structured_values(
        parsed["requested_evidence"],
        empty_check=_is_empty_evidence_value,
    )
    parsed["disagreements"] = _dedupe_structured_values(
        parsed["disagreements"],
        empty_check=_is_empty_structured_list_value,
    )
    for key in (
        "findings",
        "risks",
        "next_codex_actions",
        "files_changed",
        "tests_to_run",
        "ranked_findings",
        "evidence_references",
        "verification_hints",
    ):
        parsed[key] = _dedupe_structured_values(parsed[key])
    if parsed["status"] == "needs_codex_input" and not parsed["requested_evidence"]:
        parsed["requested_evidence"].append(parsed["summary"] or text.strip())
    if not parsed["findings"] and parsed["summary"]:
        parsed["findings"].append(parsed["summary"])
    if not parsed["ranked_findings"] and parsed["findings"]:
        parsed["ranked_findings"] = list(parsed["findings"])
    return parsed


def _join_evidence(parts: Iterable[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _as_completion(value: Any, *, estimated_input_chars: int) -> CompletionResult:
    if isinstance(value, CompletionResult):
        return value
    content = getattr(value, "content", None)
    if content is None:
        content = str(value)
    usage = CompletionUsage.from_raw(
        getattr(value, "usage", None),
        estimated_input_chars=getattr(value, "estimated_input_chars", estimated_input_chars),
        estimated_output_chars=getattr(value, "estimated_output_chars", len(str(content))),
    )
    return CompletionResult(content=str(content), usage=usage)


def _role_from_phase(phase: str) -> str:
    return phase.split(":", 1)[0] if ":" in phase else phase


def _is_empty_evidence_value(value: str) -> bool:
    normalized = _clean_markdown_scalar(value).strip().lower()
    empty_markers = {
        "none",
        "n/a",
        "na",
        "not needed",
        "no additional evidence",
        "no additional evidence needed",
        "sufficient evidence present",
    }
    return (
        normalized in empty_markers
        or normalized.startswith("none -")
        or normalized.startswith("none –")
        or normalized.startswith("none (")
        or normalized.startswith("none required")
    )


def _is_empty_structured_list_value(value: str) -> bool:
    normalized = _clean_markdown_scalar(value).strip().lower()
    return _is_empty_evidence_value(normalized) or normalized in {
        "no disagreement",
        "no disagreements",
        "not applicable",
        "not present",
    }


def _dedupe_structured_values(
    values: Sequence[str],
    *,
    empty_check: Optional[Any] = None,
) -> List[str]:
    deduped = []
    seen = set()
    for value in values:
        cleaned = _clean_markdown_scalar(str(value))
        if not cleaned:
            continue
        if empty_check and empty_check(cleaned):
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _split_list_value(value: str) -> List[str]:
    values = []
    for part in value.replace(";", ",").split(","):
        cleaned = _clean_markdown_scalar(part)
        if cleaned:
            values.append(cleaned)
    return values


def _clean_markdown_scalar(value: str) -> str:
    cleaned = value.strip()
    while cleaned.startswith("- ") or cleaned.startswith("* "):
        cleaned = cleaned[2:].strip()
    while cleaned.startswith("*"):
        cleaned = cleaned[1:].strip()
    while cleaned.endswith("*"):
        cleaned = cleaned[:-1].strip()
    while cleaned.startswith("*") and cleaned.endswith("*") and len(cleaned) > 1:
        cleaned = cleaned.strip("*").strip()
    return cleaned


def _clean_summary_scalar(value: str) -> str:
    cleaned = _clean_markdown_scalar(value)
    lowered = cleaned.lower()
    summary_marker = ":summary:"
    if lowered.startswith(":status:") and summary_marker in lowered:
        marker_index = lowered.find(summary_marker)
        cleaned = cleaned[marker_index + len(summary_marker) :].strip()
        lowered = cleaned.lower()
    for marker in (
        ":ranked_finding:",
        ":ranked_findings:",
        ":finding:",
        ":findings:",
        ":risk:",
        ":risks:",
        ":evidence_reference:",
        ":evidence_references:",
        ":requested_evidence:",
        ":verification_hint:",
        ":verification_hints:",
        ":disagreement:",
        ":disagreements:",
        ":confidence:",
    ):
        marker_index = lowered.find(marker)
        if marker_index > 0:
            cleaned = cleaned[:marker_index].strip()
            break
    return cleaned


def _clean_patch_draft(value: str) -> str:
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped in {"|", "** |", "**|", "**"}:
            continue
        if stripped.startswith("```"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    while cleaned.startswith("*") and "\n" in cleaned:
        cleaned = cleaned.lstrip("*").strip()
    return cleaned


def _looks_unsafe_task(text: str) -> bool:
    lowered = text.lower()
    for benign_phrase in (
        "no secrets",
        "no secret",
        "no api keys",
        "no api key",
        "no passwords",
        "no password",
        "no private keys",
        "no private key",
        "no live infrastructure",
        "no live infra",
        "no active repo writes",
        "do not access secrets",
        "do not use secrets",
        "do not mutate live infrastructure",
    ):
        lowered = lowered.replace(benign_phrase, "")
    unsafe_terms = [
        "production deploy",
        "live azure",
        "live infrastructure mutation",
        "delete production",
        "private key",
        "api key",
        "password",
        "secret",
        "run arbitrary",
    ]
    return any(term in lowered for term in unsafe_terms)


def _run_git(command: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"external repo scan git step failed: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"external repo scan git step failed: {detail}")


def _is_external_scan_candidate(path: Path) -> bool:
    blocked_parts = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
    if blocked_parts.intersection(path.parts):
        return False
    if path.name == ".env" or path.name.startswith(".env."):
        return False
    if path.name.endswith((".key", ".pem")):
        return False
    if path.suffix.lower() in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".rst",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".php",
        ".sh",
        ".sql",
        ".html",
        ".css",
    }:
        return True
    return path.name in {"README", "LICENSE", "Makefile", "Dockerfile"}


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
