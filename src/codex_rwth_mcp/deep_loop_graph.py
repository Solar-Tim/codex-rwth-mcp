from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from .prompts import (
    deep_debug_map_prompt,
    deep_diff_map_prompt,
    repo_map_prompt,
)

MAX_SYNTHESIS_PROMPT_CHARS = 80_000
MAX_ROLE_OUTPUT_CHARS = 12_000


class DeepLoopState(TypedDict, total=False):
    tool_name: str
    logs: str
    diff: str
    question: str
    context: str
    failing_command: str
    file_paths: Sequence[str]
    file_tree: str
    repo_root: str
    task: str
    constraints: str
    test_command: str
    analysis_depth: str
    evidence_text: str
    safety_notes: List[str]
    input_text: str
    chunks: List[str]
    roles_used: List[str]
    map_outputs: List[str]
    role_outputs: Dict[str, List[str]]
    synthesizer_output: str
    critic_output: str
    final_text: str
    result: Dict[str, Any]


class DeepLoopGraphRunner:
    def __init__(self, service: Any):
        self._service = service
        self._debug_graph = self._build_graph(include_critic=True)
        self._diff_graph = self._build_graph(include_critic=True)
        self._repo_map_graph = self._build_graph(include_critic=False)
        self._coding_task_graph = self._build_graph(include_critic=True)

    async def deep_debug_loop(
        self,
        *,
        logs: str,
        context: str = "",
        failing_command: str = "",
        file_paths: Optional[Sequence[str]] = None,
        repo_root: str = "",
        analysis_depth: str = "deep",
    ) -> Dict[str, Any]:
        state = await self._debug_graph.ainvoke(
            {
                "tool_name": "deep_debug_loop",
                "logs": logs,
                "context": context,
                "failing_command": failing_command,
                "file_paths": file_paths or [],
                "repo_root": repo_root,
                "analysis_depth": analysis_depth,
            }
        )
        return state["result"]

    async def deep_diff_review(
        self,
        *,
        diff: str = "",
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
        repo_root: str = "",
        analysis_depth: str = "deep",
    ) -> Dict[str, Any]:
        state = await self._diff_graph.ainvoke(
            {
                "tool_name": "deep_diff_review",
                "diff": diff,
                "context": context,
                "file_paths": file_paths or [],
                "repo_root": repo_root,
                "analysis_depth": analysis_depth,
            }
        )
        return state["result"]

    async def repo_map_loop(
        self,
        *,
        question: str,
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        context: str = "",
        repo_root: str = "",
        analysis_depth: str = "deep",
    ) -> Dict[str, Any]:
        state = await self._repo_map_graph.ainvoke(
            {
                "tool_name": "repo_map_loop",
                "question": question,
                "file_paths": file_paths or [],
                "file_tree": file_tree,
                "context": context,
                "repo_root": repo_root,
                "analysis_depth": analysis_depth,
            }
        )
        return state["result"]

    async def generic_repo_loop(
        self,
        *,
        tool_name: str,
        question: str,
        file_paths: Optional[Sequence[str]] = None,
        file_tree: str = "",
        context: str = "",
        repo_root: str = "",
        analysis_depth: str = "deep",
    ) -> Dict[str, Any]:
        state = await self._repo_map_graph.ainvoke(
            {
                "tool_name": tool_name,
                "question": question,
                "file_paths": file_paths or [],
                "file_tree": file_tree,
                "context": context,
                "repo_root": repo_root,
                "analysis_depth": analysis_depth,
            }
        )
        return state["result"]

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
        analysis_depth: str = "deep",
    ) -> Dict[str, Any]:
        state = await self._coding_task_graph.ainvoke(
            {
                "tool_name": "coding_task_loop",
                "task": task,
                "question": task,
                "file_paths": file_paths or [],
                "file_tree": file_tree,
                "context": context,
                "repo_root": repo_root,
                "constraints": constraints,
                "test_command": test_command,
                "analysis_depth": analysis_depth,
            }
        )
        return state["result"]

    def _build_graph(self, *, include_critic: bool):
        graph = StateGraph(DeepLoopState)
        graph.add_node("prepare_evidence", self._prepare_evidence)
        graph.add_node("map_chunks", self._map_chunks)
        graph.add_node("synthesize", self._synthesize)
        graph.add_node("critic", self._critic)
        graph.add_node("finalize", self._finalize)
        graph.add_node("parse_result", self._parse_result)
        graph.set_entry_point("prepare_evidence")
        graph.add_edge("prepare_evidence", "map_chunks")
        graph.add_edge("map_chunks", "synthesize")
        graph.add_conditional_edges(
            "synthesize",
            self._after_synthesize,
            {
                "critic": "critic",
                "finalize": "finalize",
            },
        )
        graph.add_edge("critic", "finalize")
        graph.add_edge("finalize", "parse_result")
        graph.add_edge("parse_result", END)
        return graph.compile()

    async def _prepare_evidence(self, state: DeepLoopState) -> Dict[str, Any]:
        from .deep_loop import (
            FileEvidenceLoader,
            _chunk_diff,
            _chunk_text,
            _join_evidence,
        )

        tool_name = state["tool_name"]
        roles = self._roles_for_state(state)
        self._service._set_roles_used(roles)
        evidence = FileEvidenceLoader(
            self._service._resolve_repo_root(state.get("repo_root", ""))
        ).load(state.get("file_paths", []))
        if tool_name == "deep_debug_loop":
            input_text = _join_evidence(
                [
                    state.get("logs", ""),
                    state.get("context", ""),
                    state.get("failing_command", ""),
                    evidence.text,
                ]
            )
            chunks = self._select_chunks(_chunk_text(input_text), roles, state)
        elif tool_name == "deep_diff_review":
            input_text = _join_evidence(
                [state.get("diff", ""), state.get("context", ""), evidence.text]
            )
            chunks = self._select_chunks(_chunk_diff(input_text), roles, state)
        elif tool_name == "coding_task_loop":
            input_text = _join_evidence(
                [
                    state.get("task", ""),
                    state.get("file_tree", ""),
                    state.get("context", ""),
                    state.get("constraints", ""),
                    state.get("test_command", ""),
                    evidence.text,
                ]
            )
            chunks = self._select_chunks(_chunk_text(input_text), roles, state)
        else:
            input_text = _join_evidence(
                [
                    state.get("question", ""),
                    state.get("file_tree", ""),
                    state.get("context", ""),
                    evidence.text,
                ]
            )
            chunks = self._select_chunks(_chunk_text(input_text), roles, state)
        return {
            "evidence_text": evidence.text,
            "safety_notes": evidence.safety_notes,
            "input_text": input_text,
            "chunks": chunks,
            "roles_used": roles,
        }

    async def _map_chunks(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        tasks = []
        task_meta = []
        for role in state.get("roles_used", ["mapper"]):
            for index, chunk in enumerate(state.get("chunks", [""]), start=1):
                task_meta.append((role, index))
                tasks.append(
                    self._service._complete_text(
                        tool_name=tool_name,
                        phase=f"{role}:map-{index}",
                        role=role,
                        user_prompt=self._role_prompt(tool_name, state, chunk, role),
                    )
                )
        outputs = await asyncio.gather(*tasks) if tasks else []
        role_outputs: Dict[str, List[str]] = {}
        for (role, _index), output in zip(task_meta, outputs):
            role_outputs.setdefault(role, []).append(output)
        return {"map_outputs": list(outputs), "role_outputs": role_outputs}

    async def _synthesize(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        return {
            "synthesizer_output": await self._service._complete_text(
                tool_name=tool_name,
                phase="synthesizer",
                role="synthesizer",
                user_prompt=self._synthesizer_prompt(tool_name, state),
            )
        }

    async def _critic(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        return {
            "critic_output": await self._service._complete_text(
                tool_name=tool_name,
                phase="critic",
                role="critic",
                user_prompt=self._critic_prompt(tool_name, state),
            )
        }

    async def _finalize(self, state: DeepLoopState) -> Dict[str, Any]:
        return {
            "final_text": "\n".join(
                part
                for part in [
                    state.get("synthesizer_output", ""),
                    state.get("critic_output", ""),
                ]
                if part
            )
        }

    async def _parse_result(self, state: DeepLoopState) -> Dict[str, Any]:
        result_text = state.get("final_text") or state.get("critic_output", "")
        return {
            "result": self._service._result_from_text(
                state["tool_name"],
                result_text,
                state.get("safety_notes", []),
            )
        }

    def _after_synthesize(self, state: DeepLoopState) -> str:
        if state.get("analysis_depth") == "fast":
            return "finalize"
        return "critic"

    def _map_prompt(self, tool_name: str, state: DeepLoopState, chunk: str) -> str:
        if tool_name == "deep_debug_loop":
            return deep_debug_map_prompt(
                logs=chunk,
                context=state.get("context", ""),
                failing_command=state.get("failing_command", ""),
            )
        if tool_name == "deep_diff_review":
            return deep_diff_map_prompt(diff=chunk, context=state.get("context", ""))
        if tool_name == "coding_task_loop":
            return (
                "You are drafting a supervised coding-task proposal for Codex. "
                "Do not claim to edit files. Analyze the evidence and propose a safe implementation.\n\n"
                f"Task:\n{state.get('task', '')}\n\n"
                f"Constraints:\n{state.get('constraints', '')}\n\n"
                f"Test command:\n{state.get('test_command', '')}\n\n"
                f"Evidence chunk:\n{chunk}"
            )
        return repo_map_prompt(
            question=state.get("question", ""),
            file_tree=state.get("file_tree", ""),
            files=chunk,
            context=state.get("context", ""),
        )

    def _role_prompt(
        self,
        tool_name: str,
        state: DeepLoopState,
        chunk: str,
        role: str,
    ) -> str:
        if role == "mapper":
            return self._map_prompt(tool_name, state, chunk)
        focus = {
            "risk_finder": "Find concrete risks, failure modes, regressions, missing evidence, and uncertainty.",
            "test_strategist": "Identify tests Codex should run or add, validation gaps, and verification hints.",
            "architecture_critic": "Critique architecture, coupling, ownership, boundaries, and design tradeoffs.",
            "patch_drafter": "Draft a supervised patch proposal only. Do not claim to edit files.",
        }[role]
        return (
            f"role: {role}\n"
            f"You are a bounded configured-provider worker for Codex. {focus}\n"
            "Return colon-prefixed fields where possible: finding, risk, evidence_reference, "
            "verification_hint, disagreement, confidence, requested_evidence. "
            "For patch_drafter, include implementation_plan, patch_draft, files_changed, tests_to_run.\n\n"
            f"Tool: {tool_name}\n"
            f"Question or task:\n{state.get('question') or state.get('task') or ''}\n\n"
            f"Context:\n{state.get('context', '')}\n\n"
            f"Evidence chunk:\n{chunk}"
        )

    def _synthesizer_prompt(self, tool_name: str, state: DeepLoopState) -> str:
        prompt = (
            "Worker-model synthesizer pass for Codex. Deduplicate, compress, rank, and preserve uncertainty. "
            "Do not invent evidence. Return colon-prefixed fields: status, summary, ranked_finding, "
            "finding, risk, evidence_reference, verification_hint, confidence, requested_evidence, "
            "implementation_plan, patch_draft, files_changed, tests_to_run.\n\n"
            f"Tool: {tool_name}\n"
            f"Analysis depth: {state.get('analysis_depth', '')}\n"
            f"Roles used: {', '.join(state.get('roles_used', []))}\n\n"
            f"Role outputs:\n{self._format_role_outputs(state)}"
        )
        return _truncate_text(prompt, MAX_SYNTHESIS_PROMPT_CHARS)

    def _critic_prompt(self, tool_name: str, state: DeepLoopState) -> str:
        prompt = (
            "Worker-model critic pass for Codex. Identify unsupported claims, missing evidence, disagreements, "
            "and overconfident conclusions. Do not make final decisions. Return colon-prefixed fields: "
            "status, summary, risk, disagreement, requested_evidence, verification_hint, confidence.\n\n"
            f"Tool: {tool_name}\n"
            f"Analysis depth: {state.get('analysis_depth', '')}\n\n"
            f"Synthesizer output:\n{state.get('synthesizer_output', '')}\n\n"
            f"Role outputs:\n{self._format_role_outputs(state)}"
        )
        return _truncate_text(prompt, MAX_SYNTHESIS_PROMPT_CHARS)

    def _format_role_outputs(self, state: DeepLoopState) -> str:
        sections = []
        for role, outputs in state.get("role_outputs", {}).items():
            compact_outputs = [
                _truncate_text(output, MAX_ROLE_OUTPUT_CHARS)
                for output in outputs
            ]
            sections.append(f"## {role}\n" + "\n\n".join(compact_outputs))
        return "\n\n".join(sections)

    def _roles_for_state(self, state: DeepLoopState) -> List[str]:
        depth = state.get("analysis_depth", "deep")
        if depth == "fast":
            roles = ["mapper"]
        elif depth == "standard":
            roles = ["mapper", "risk_finder"]
        else:
            roles = ["mapper", "risk_finder", "test_strategist", "architecture_critic"]
        if state["tool_name"] == "coding_task_loop" and depth != "fast":
            roles.append("patch_drafter")
        return roles

    def _select_chunks(
        self,
        chunks: List[str],
        roles: Sequence[str],
        state: DeepLoopState,
    ) -> List[str]:
        critic_calls = 0 if state.get("analysis_depth") == "fast" else 1
        reserved = 1 + critic_calls
        role_count = max(len(roles), 1)
        available = max(self._service._active_max_calls - reserved, 1)
        return chunks[: max(available // role_count, 1)]


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep = max(max_chars - 80, 0)
    return text[:keep].rstrip() + f"\n[truncated {len(text) - keep} chars]"
