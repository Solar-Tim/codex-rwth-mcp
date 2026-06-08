from pathlib import Path
import asyncio

import pytest

from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.deep_loop import DeepLoopService, JsonResponseCache
from codex_rwth_mcp.router import ModelRouter
from codex_rwth_mcp.usage import UsageLedger


class RoleAwareClient:
    def __init__(self):
        self.text_calls = []

    async def complete_text(self, **kwargs):
        self.text_calls.append(kwargs)
        prompt = kwargs["user_prompt"]
        if "synthesizer pass" in prompt:
            return (
                "status: complete\n"
                "summary: synthesized handoff\n"
                "ranked_finding: src/app.py is the main entry point\n"
                "evidence_reference: src/app.py\n"
                "verification_hint: run pytest tests/test_app.py\n"
                "confidence: medium\n"
            )
        if "critic pass" in prompt:
            return (
                "status: complete\n"
                "summary: critic accepted with caveats\n"
                "disagreement: mapper and architecture critic disagree on coupling severity\n"
                "risk: migration risk lacks tests\n"
            )
        if "role: mapper" in prompt:
            return "role: mapper\nfinding: src/app.py handles the flow\nevidence_reference: src/app.py\nconfidence: medium"
        if "role: risk_finder" in prompt:
            return "role: risk_finder\nrisk: migration risk lacks tests\nevidence_reference: tests/test_app.py\nconfidence: low"
        if "role: test_strategist" in prompt:
            return "role: test_strategist\nverification_hint: run pytest tests/test_app.py\nevidence_reference: tests/test_app.py"
        if "role: architecture_critic" in prompt:
            return "role: architecture_critic\ndisagreement: mapper underweights service coupling\nevidence_reference: src/service.py"
        if "role: patch_drafter" in prompt:
            return "role: patch_drafter\npatch_draft: diff --git a/app.py b/app.py\nfiles_changed: app.py"
        return "status: complete\nsummary: final judged result\nfinding: fallback"


class ConcurrencyTrackingClient(RoleAwareClient):
    def __init__(self):
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def complete_text(self, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        try:
            return await super().complete_text(**kwargs)
        finally:
            self.active -= 1


def make_config(tmp_path: Path) -> AppConfig:
    tool_names = (
        "deep_debug_loop",
        "deep_diff_review",
        "repo_map_loop",
        "deep_repo_review_loop",
        "deep_test_strategy_loop",
        "deep_architecture_critic",
        "coding_task_loop",
        "external_repo_scan_loop",
    )
    return AppConfig(
        rwth=RwthConfig(base_url="https://api.example/v1"),
        models={"text": ModelConfig(id="rwth-text", max_input_chars=200_000)},
        tools={
            name: ToolConfig(routes=[RouteRule(model="text", max_input_chars=200_000)])
            for name in tool_names
        },
        repo_roots={"repo": tmp_path},
    )


def make_service(tmp_path: Path, client: RoleAwareClient) -> DeepLoopService:
    config = make_config(tmp_path)
    return DeepLoopService(
        config=config,
        router=ModelRouter(config),
        client=client,
        repo_root=tmp_path,
        cache=JsonResponseCache(tmp_path / "cache"),
        usage_ledger=UsageLedger(tmp_path / "usage.jsonl"),
    )


@pytest.mark.asyncio
async def test_default_deep_depth_uses_parallel_roles_and_judged_metadata(tmp_path: Path):
    client = RoleAwareClient()
    service = make_service(tmp_path, client)

    result = await service.deep_repo_review_loop(
        question="Review this repository",
        file_tree="src/app.py\ntests/test_app.py",
    )

    assert result["analysis_depth"] == "deep"
    assert result["roles_used"] == [
        "mapper",
        "risk_finder",
        "test_strategist",
        "architecture_critic",
    ]
    assert "src/app.py is the main entry point" in result["ranked_findings"]
    assert "src/app.py" in result["evidence_references"]
    assert result["verification_hints"] == ["run pytest tests/test_app.py"]
    assert result["disagreements"]
    assert result["confidence"] == "medium"
    assert result["calls_used"] <= 16
    assert all("role" in event for event in result["usage_by_phase"])


@pytest.mark.asyncio
async def test_fast_depth_uses_smaller_budget_and_mapper_only(tmp_path: Path):
    client = RoleAwareClient()
    service = make_service(tmp_path, client)

    result = await service.repo_map_loop(
        question="Map quickly",
        file_tree="src/app.py",
        analysis_depth="fast",
    )

    assert result["analysis_depth"] == "fast"
    assert result["roles_used"] == ["mapper"]
    assert result["calls_used"] <= 4


@pytest.mark.asyncio
async def test_coding_task_deep_depth_is_only_tool_with_patch_drafter_role(tmp_path: Path):
    client = RoleAwareClient()
    service = make_service(tmp_path, client)
    (tmp_path / "app.py").write_text("print('old')\n", encoding="utf-8")

    result = await service.coding_task_loop(
        task="Draft a patch",
        file_paths=["app.py"],
        analysis_depth="deep",
        constraints="No secrets, no live infrastructure, no active repo writes.",
    )

    assert "patch_drafter" in result["roles_used"]
    assert "patch_drafter" in [event["role"] for event in result["usage_by_phase"]]


@pytest.mark.asyncio
async def test_invalid_analysis_depth_is_blocked_without_model_call(tmp_path: Path):
    client = RoleAwareClient()
    service = make_service(tmp_path, client)

    result = await service.repo_map_loop(
        question="Map",
        analysis_depth="maximum",
    )

    assert result["status"] == "blocked"
    assert result["safety_notes"] == [
        "invalid analysis_depth 'maximum'; use one of fast, standard, deep, exhaustive"
    ]
    assert client.text_calls == []


@pytest.mark.asyncio
async def test_parallel_role_fanout_throttles_live_model_concurrency(tmp_path: Path):
    client = ConcurrencyTrackingClient()
    service = make_service(tmp_path, client)

    result = await service.deep_repo_review_loop(
        question="Review this repository",
        file_tree="src/app.py\ntests/test_app.py",
        analysis_depth="deep",
    )

    assert result["status"] == "complete"
    assert client.max_active <= 2


def test_synthesizer_prompt_compacts_large_role_outputs(tmp_path: Path):
    client = RoleAwareClient()
    runner = make_service(tmp_path, client)._graph_runner
    state = {
        "tool_name": "repo_map_loop",
        "analysis_depth": "exhaustive",
        "roles_used": ["mapper", "risk_finder", "test_strategist", "architecture_critic"],
        "role_outputs": {
            "mapper": ["mapper evidence " + ("a" * 80_000)],
            "risk_finder": ["risk evidence " + ("b" * 80_000)],
            "test_strategist": ["test evidence " + ("c" * 80_000)],
            "architecture_critic": ["arch evidence " + ("d" * 80_000)],
        },
    }

    prompt = runner._synthesizer_prompt("repo_map_loop", state)

    assert len(prompt) < 90_000
    assert "[truncated " in prompt
