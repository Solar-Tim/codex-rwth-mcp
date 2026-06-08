from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, TypedDict

from langgraph.graph import END, StateGraph

from .prompts import (
    deep_debug_final_prompt,
    deep_debug_map_prompt,
    deep_diff_final_prompt,
    deep_diff_map_prompt,
    repo_map_final_prompt,
    repo_map_prompt,
)


class DeepLoopState(TypedDict, total=False):
    tool_name: str
    logs: str
    diff: str
    question: str
    context: str
    failing_command: str
    file_paths: Sequence[str]
    file_tree: str
    evidence_text: str
    safety_notes: List[str]
    input_text: str
    chunks: List[str]
    map_outputs: List[str]
    critic_output: str
    final_text: str
    result: Dict[str, Any]


class DeepLoopGraphRunner:
    def __init__(self, service: Any):
        self._service = service
        self._debug_graph = self._build_graph(include_critic=True)
        self._diff_graph = self._build_graph(include_critic=True)
        self._repo_map_graph = self._build_graph(include_critic=False)

    async def deep_debug_loop(
        self,
        *,
        logs: str,
        context: str = "",
        failing_command: str = "",
        file_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        state = await self._debug_graph.ainvoke(
            {
                "tool_name": "deep_debug_loop",
                "logs": logs,
                "context": context,
                "failing_command": failing_command,
                "file_paths": file_paths or [],
            }
        )
        return state["result"]

    async def deep_diff_review(
        self,
        *,
        diff: str = "",
        context: str = "",
        file_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        state = await self._diff_graph.ainvoke(
            {
                "tool_name": "deep_diff_review",
                "diff": diff,
                "context": context,
                "file_paths": file_paths or [],
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
    ) -> Dict[str, Any]:
        state = await self._repo_map_graph.ainvoke(
            {
                "tool_name": "repo_map_loop",
                "question": question,
                "file_paths": file_paths or [],
                "file_tree": file_tree,
                "context": context,
            }
        )
        return state["result"]

    def _build_graph(self, *, include_critic: bool):
        graph = StateGraph(DeepLoopState)
        graph.add_node("prepare_evidence", self._prepare_evidence)
        graph.add_node("map_chunks", self._map_chunks)
        graph.add_node("finalize", self._finalize)
        graph.add_node("parse_result", self._parse_result)
        graph.set_entry_point("prepare_evidence")
        graph.add_edge("prepare_evidence", "map_chunks")
        if include_critic:
            graph.add_node("critic", self._critic)
            graph.add_edge("map_chunks", "critic")
            graph.add_conditional_edges(
                "critic",
                self._after_critic,
                {
                    "finalize": "finalize",
                    "parse_result": "parse_result",
                },
            )
        else:
            graph.add_edge("map_chunks", "finalize")
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
        evidence = FileEvidenceLoader(self._service._repo_root).load(state.get("file_paths", []))
        if tool_name == "deep_debug_loop":
            input_text = _join_evidence(
                [
                    state.get("logs", ""),
                    state.get("context", ""),
                    state.get("failing_command", ""),
                    evidence.text,
                ]
            )
            chunks = _chunk_text(input_text)[: self._service._max_calls - 2]
        elif tool_name == "deep_diff_review":
            input_text = _join_evidence(
                [state.get("diff", ""), state.get("context", ""), evidence.text]
            )
            chunks = _chunk_diff(input_text)[: self._service._max_calls - 2]
        else:
            input_text = _join_evidence(
                [
                    state.get("question", ""),
                    state.get("file_tree", ""),
                    state.get("context", ""),
                    evidence.text,
                ]
            )
            chunks = _chunk_text(input_text)[: self._service._max_calls - 1]
        return {
            "evidence_text": evidence.text,
            "safety_notes": evidence.safety_notes,
            "input_text": input_text,
            "chunks": chunks,
        }

    async def _map_chunks(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        outputs = []
        for index, chunk in enumerate(state.get("chunks", [""]), start=1):
            outputs.append(
                await self._service._complete_text(
                    tool_name=tool_name,
                    phase=f"map-{index}",
                    user_prompt=self._map_prompt(tool_name, state, chunk),
                )
            )
        return {"map_outputs": outputs}

    async def _critic(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        return {
            "critic_output": await self._service._complete_text(
                tool_name=tool_name,
                phase="critic",
                user_prompt=self._final_prompt(tool_name, state, mode="critic"),
            )
        }

    async def _finalize(self, state: DeepLoopState) -> Dict[str, Any]:
        tool_name = state["tool_name"]
        return {
            "final_text": await self._service._complete_text(
                tool_name=tool_name,
                phase="final",
                user_prompt=self._final_prompt(tool_name, state, mode="final"),
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

    def _after_critic(self, state: DeepLoopState) -> str:
        if "needs_codex_input" in state.get("critic_output", "").lower():
            return "parse_result"
        return "finalize"

    def _map_prompt(self, tool_name: str, state: DeepLoopState, chunk: str) -> str:
        if tool_name == "deep_debug_loop":
            return deep_debug_map_prompt(
                logs=chunk,
                context=state.get("context", ""),
                failing_command=state.get("failing_command", ""),
            )
        if tool_name == "deep_diff_review":
            return deep_diff_map_prompt(diff=chunk, context=state.get("context", ""))
        return repo_map_prompt(
            question=state.get("question", ""),
            file_tree=state.get("file_tree", ""),
            files=chunk,
            context=state.get("context", ""),
        )

    def _final_prompt(self, tool_name: str, state: DeepLoopState, *, mode: str) -> str:
        summaries = list(state.get("map_outputs", []))
        if mode == "final" and state.get("critic_output"):
            summaries.append(state["critic_output"])
        if tool_name == "deep_debug_loop":
            return deep_debug_final_prompt(
                summaries="\n\n".join(summaries),
                context=state.get("context", ""),
                safety_notes=state.get("safety_notes", []),
                mode=mode,
            )
        if tool_name == "deep_diff_review":
            return deep_diff_final_prompt(
                summaries="\n\n".join(summaries),
                context=state.get("context", ""),
                safety_notes=state.get("safety_notes", []),
                mode=mode,
            )
        return repo_map_final_prompt(
            summaries="\n\n".join(summaries),
            question=state.get("question", ""),
            safety_notes=state.get("safety_notes", []),
        )
