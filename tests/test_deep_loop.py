from pathlib import Path

import pytest

from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.deep_loop import DeepLoopService, FileEvidenceLoader, JsonResponseCache
from codex_rwth_mcp.router import ModelRouter


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


def test_file_evidence_loader_allows_repo_text_files(tmp_path: Path):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")

    result = FileEvidenceLoader(tmp_path).load(["src/app.py"])

    assert "src/app.py" in result.text
    assert "print('hello')" in result.text
    assert result.safety_notes == []


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.txt",
        ".env",
        ".git/config",
        ".venv/pyvenv.cfg",
        "secret.key",
        "cert.pem",
        "config/routing.local.yaml",
    ],
)
def test_file_evidence_loader_blocks_unsafe_paths(tmp_path: Path, relative_path: str):
    target = (tmp_path / relative_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret", encoding="utf-8")

    result = FileEvidenceLoader(tmp_path).load([relative_path])

    assert result.text == ""
    assert result.safety_notes


def test_file_evidence_loader_blocks_binary_and_oversized_files(tmp_path: Path):
    binary = tmp_path / "image.png"
    binary.write_bytes(b"\x89PNG\x00\x01")
    large = tmp_path / "large.log"
    large.write_text("x" * 200, encoding="utf-8")

    result = FileEvidenceLoader(tmp_path, max_file_bytes=100).load(["image.png", "large.log"])

    assert result.text == ""
    assert len(result.safety_notes) == 2


@pytest.mark.asyncio
async def test_deep_debug_loop_completes_with_bounded_calls_and_cache(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "map summary: missing DATABASE_URL",
            "critic: evidence is sufficient",
            "status: complete\nsummary: DATABASE_URL is missing\nfinding: worker lacks env",
        ]
    )
    service = make_service(tmp_path, client)

    first = await service.deep_debug_loop(
        logs="ERROR worker failed: missing DATABASE_URL",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )
    second = await service.deep_debug_loop(
        logs="ERROR worker failed: missing DATABASE_URL",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )

    assert first["status"] == "complete"
    assert first["calls_used"] <= 8
    assert first["model_ids"] == ["rwth-text"]
    assert second["cache_hits"] >= 1
    assert len(client.text_calls) == 2
    assert "ERROR worker failed" not in str(second["cache_hits"])
    assert "DATABASE_URL" not in str(second["cache_hits"])


@pytest.mark.asyncio
async def test_deep_debug_loop_cache_misses_when_input_changes(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "map summary: first",
            "status: complete\nsummary: first",
            "map summary: second",
            "status: complete\nsummary: second",
        ]
    )
    service = make_service(tmp_path, client)

    first = await service.deep_debug_loop(
        logs="ERROR first failure",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )
    second = await service.deep_debug_loop(
        logs="ERROR second failure",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )

    assert first["cache_hits"] == 0
    assert second["cache_hits"] == 0
    assert len(client.text_calls) == 4


@pytest.mark.asyncio
async def test_deep_debug_loop_requests_codex_input_when_evidence_is_missing(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "map summary: import error without file context",
            "status: needs_codex_input\nrequested_evidence: provide src/app.py and full traceback",
        ]
    )
    result = await make_service(tmp_path, client).deep_debug_loop(
        logs="ImportError: cannot import name settings",
        context="pytest",
        failing_command="pytest",
        file_paths=[],
        analysis_depth="fast",
    )

    assert result["status"] == "needs_codex_input"
    assert result["requested_evidence"]
    assert result["next_codex_actions"]


@pytest.mark.asyncio
async def test_deep_diff_review_chunks_and_merges_large_diff(tmp_path: Path):
    client = SequencedRwthClient(
        [
            "chunk 1 risk: config changed",
            "chunk 2 risk: tests missing",
            "status: complete\nsummary: review complete\nrisk: missing tests",
        ]
    )
    diff = "\n".join([f"+line {index}" for index in range(160)])

    result = await make_service(tmp_path, client).deep_diff_review(
        diff=diff,
        context="PR review",
        file_paths=[],
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert result["calls_used"] >= 2
    assert result["calls_used"] <= 4
    assert result["risks"]


@pytest.mark.asyncio
async def test_repo_map_loop_reads_allowed_files_and_returns_ranked_findings(tmp_path: Path):
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service: pass\n", encoding="utf-8")
    client = SequencedRwthClient(
        [
            "file src/service.py defines Service",
            "status: complete\nsummary: service layer is relevant\nfinding: src/service.py",
        ]
    )

    result = await make_service(tmp_path, client).repo_map_loop(
        question="Where is the service layer?",
        file_paths=["src/service.py"],
        file_tree="src/service.py",
        context="pytest",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert "src/service.py" in client.text_calls[0]["user_prompt"]
    assert result["findings"]
