from pathlib import Path

import pytest

from codex_rwth_mcp.deep_loop import DeepLoopService, JsonResponseCache
from codex_rwth_mcp.deep_loop_graph import DeepLoopGraphRunner
from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.router import ModelRouter


EXPECTED_RESULT_KEYS = {
    "tool",
    "status",
    "summary",
    "findings",
    "risks",
    "requested_evidence",
    "next_codex_actions",
    "implementation_plan",
    "patch_draft",
    "files_changed",
    "tests_to_run",
    "ranked_findings",
    "evidence_references",
    "disagreements",
    "confidence",
    "verification_hints",
    "analysis_depth",
    "roles_used",
    "calls_used",
    "cache_hits",
    "model_ids",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_input_chars",
    "estimated_output_chars",
    "usage_by_phase",
    "safety_notes",
}


class SequencedRwthClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.text_calls = []

    async def complete_text(self, **kwargs):
        self.text_calls.append(kwargs)
        if not self.responses:
            return "status: complete\nsummary: fallback"
        return self.responses.pop(0)


def make_config() -> AppConfig:
    tools = {
        name: ToolConfig(
            routes=[RouteRule(model="text", max_input_chars=100_000)],
            max_output_tokens=700,
            temperature=0.1,
        )
        for name in ("deep_debug_loop", "deep_diff_review", "repo_map_loop")
    }
    return AppConfig(
        rwth=RwthConfig(base_url="https://api.example/v1"),
        models={"text": ModelConfig(id="rwth-text", max_input_chars=100_000)},
        tools=tools,
    )


def make_service(tmp_path: Path, client: SequencedRwthClient) -> DeepLoopService:
    config = make_config()
    return DeepLoopService(
        config=config,
        router=ModelRouter(config),
        client=client,
        repo_root=tmp_path,
        cache=JsonResponseCache(tmp_path / "cache"),
    )


def test_graph_runner_imports_and_compiles():
    assert DeepLoopGraphRunner.__name__ == "DeepLoopGraphRunner"


@pytest.mark.asyncio
async def test_service_uses_langgraph_runner_for_debug_loop(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "map summary: missing DATABASE_URL",
            "critic: evidence is sufficient",
            "status: complete\nsummary: DATABASE_URL is missing\nfinding: worker lacks env",
        ]
    )
    service = make_service(tmp_path, client)

    result = await service.deep_debug_loop(
        logs="ERROR worker failed: missing DATABASE_URL",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )

    assert isinstance(service._graph_runner, DeepLoopGraphRunner)
    assert set(result) == EXPECTED_RESULT_KEYS
    assert result["status"] == "complete"
    assert result["calls_used"] <= 8
    assert len(client.text_calls) == 2


@pytest.mark.asyncio
async def test_graph_runner_routes_debug_loop_to_codex_input(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "map summary: import error without file context",
            "status: needs_codex_input\nrequested_evidence: provide src/app.py",
        ]
    )
    service = make_service(tmp_path, client)

    result = await service.deep_debug_loop(
        logs="ImportError: cannot import name settings",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )

    assert result["status"] == "needs_codex_input"
    assert result["requested_evidence"] == ["provide src/app.py"]
    assert result["next_codex_actions"]
    assert len(client.text_calls) == 2


@pytest.mark.asyncio
async def test_graph_runner_chunks_diff_and_preserves_cache_metadata(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "chunk 1 risk: config changed",
            "chunk 2 risk: tests missing",
            "critic: check migrations",
            "status: complete\nsummary: review complete\nrisk: missing tests",
        ]
    )
    service = make_service(tmp_path, client)
    diff = "\n".join([f"+line {index}" for index in range(160)])

    first = await service.deep_diff_review(
        diff=diff,
        context="PR review",
        file_paths=[],
        analysis_depth="fast",
    )
    second = await service.deep_diff_review(
        diff=diff,
        context="PR review",
        file_paths=[],
        analysis_depth="fast",
    )

    assert set(first) == EXPECTED_RESULT_KEYS
    assert first["status"] == "complete"
    assert first["calls_used"] == 3
    assert second["cache_hits"] == 3
    assert second["calls_used"] == 0
    assert "PR review" not in str(second["cache_hits"])
    assert len(client.text_calls) == 3


@pytest.mark.asyncio
async def test_graph_runner_repo_map_reads_allowed_files(tmp_path: Path):
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service: pass\n", encoding="utf-8")
    client = SequencedRwthClient(
        [
            "file src/service.py defines Service",
            "status: complete\nsummary: service layer is relevant\nfinding: src/service.py",
        ]
    )
    service = make_service(tmp_path, client)

    result = await service.repo_map_loop(
        question="Where is the service layer?",
        file_paths=["src/service.py"],
        file_tree="src/service.py",
        context="pytest",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert "src/service.py" in client.text_calls[0]["user_prompt"]
    assert result["findings"] == ["src/service.py"]
