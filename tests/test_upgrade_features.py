from pathlib import Path

import pytest

from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.deep_loop import DeepLoopService, JsonResponseCache, _parse_handoff
from codex_rwth_mcp.router import ModelRouter
from codex_rwth_mcp.usage import CompletionUsage, UsageLedger


class UsageRwthClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.text_calls = []

    async def complete_text(self, **kwargs):
        self.text_calls.append(kwargs)
        content, usage = self.responses.pop(0)
        return type(
            "Completion",
            (),
            {
                "content": content,
                "usage": usage,
                "estimated_input_chars": len(kwargs["user_prompt"]),
                "estimated_output_chars": len(content),
            },
        )()


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
        models={"text": ModelConfig(id="rwth-text", max_input_chars=100_000)},
        tools={
            name: ToolConfig(routes=[RouteRule(model="text", max_input_chars=100_000)])
            for name in tool_names
        },
        repo_roots={"other": tmp_path / "other"},
    )


def make_service(tmp_path: Path, client: UsageRwthClient) -> DeepLoopService:
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
async def test_requested_evidence_none_does_not_force_codex_input(tmp_path: Path):
    client = UsageRwthClient(
        [
            ("map: enough", {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
            (
                "status: complete\nsummary: mapped\nrequested_evidence: none - sufficient evidence present",
                {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            ),
        ]
    )

    result = await make_service(tmp_path, client).repo_map_loop(
        question="Map repo",
        file_tree="README.md",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert result["requested_evidence"] == []


@pytest.mark.asyncio
async def test_usage_fields_and_usage_report_are_recorded(tmp_path: Path):
    client = UsageRwthClient(
        [
            ("map: enough", {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}),
            (
                "status: complete\nsummary: mapped",
                {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18},
            ),
        ]
    )
    service = make_service(tmp_path, client)

    result = await service.repo_map_loop(
        question="Map repo",
        file_tree="README.md",
        analysis_depth="fast",
    )
    report = service.usage_report(days=7, group_by="tool")

    assert result["prompt_tokens"] == 24
    assert result["completion_tokens"] == 8
    assert result["total_tokens"] == 32
    assert result["usage_by_phase"][0]["phase"] == "mapper:map-1"
    assert report["totals"]["calls"] == 2
    assert report["groups"]["repo_map_loop"]["total_tokens"] == 32


@pytest.mark.asyncio
async def test_deep_loop_reads_configured_repo_root_by_name(tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "README.md").write_text("other repo\n", encoding="utf-8")
    client = UsageRwthClient(
        [
            ("map: saw file", {}),
            ("status: complete\nsummary: mapped", {}),
        ]
    )

    result = await make_service(tmp_path, client).repo_map_loop(
        question="Map other",
        file_paths=["README.md"],
        repo_root="other",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert "other repo" in client.text_calls[0]["user_prompt"]


@pytest.mark.asyncio
async def test_unknown_repo_root_is_blocked(tmp_path: Path):
    client = UsageRwthClient([("unused", {})])

    result = await make_service(tmp_path, client).repo_map_loop(
        question="Map other",
        file_paths=["README.md"],
        repo_root="/tmp",
    )

    assert result["status"] == "blocked"
    assert result["safety_notes"]
    assert client.text_calls == []


@pytest.mark.asyncio
async def test_coding_task_loop_returns_patch_draft_without_mutating_repo(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text("print('old')\n", encoding="utf-8")
    client = UsageRwthClient(
        [
            ("plan: change print", {}),
            (
                "status: complete\nsummary: patch ready\nimplementation_plan: update app.py\n"
                "patch_draft: diff --git a/app.py b/app.py\\n--- a/app.py\\n+++ b/app.py\\n@@ -1 +1 @@\\n-print('old')\\n+print('new')\n"
                "files_changed: app.py\n"
                "tests_to_run: python app.py",
                {},
            ),
        ]
    )

    result = await make_service(tmp_path, client).coding_task_loop(
        task="Change old to new",
        file_paths=["app.py"],
        test_command="python app.py",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert "diff --git" in result["patch_draft"]
    assert result["files_changed"] == ["app.py"]
    assert source.read_text(encoding="utf-8") == "print('old')\n"


@pytest.mark.asyncio
async def test_coding_task_loop_allows_negated_secret_and_live_infra_constraints(tmp_path: Path):
    source = tmp_path / "README.md"
    source.write_text("# Demo\n", encoding="utf-8")
    client = UsageRwthClient(
        [
            ("plan: docs only", {}),
            (
                "status: complete\nsummary: patch ready\nimplementation_plan: update README.md\n"
                "patch_draft: diff --git a/README.md b/README.md\n"
                "files_changed: README.md\n"
                "tests_to_run: none",
                {},
            ),
        ]
    )

    result = await make_service(tmp_path, client).coding_task_loop(
        task="Draft a documentation-only README note.",
        file_paths=["README.md"],
        constraints="No live infrastructure, no secrets, no active repo writes.",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert client.text_calls


def test_parse_handoff_collects_multiline_requested_evidence():
    parsed = _parse_handoff(
        "status: needs_codex_input\n"
        "summary: need more files\n"
        "requested_evidence:\n"
        "- apps/azure-ingestion/function_app.py\n"
        "- docs/status/INGESTION_STATUS.md\n"
        "next_codex_action: gather files"
    )

    assert parsed["requested_evidence"] == [
        "apps/azure-ingestion/function_app.py",
        "docs/status/INGESTION_STATUS.md",
    ]
    assert parsed["status"] == "needs_codex_input"


def test_parse_handoff_collects_multiline_patch_draft():
    parsed = _parse_handoff(
        "status: complete\n"
        "summary: patch ready\n"
        "patch_draft: |\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Demo\n"
        "+Use MCP repo mapping before broad changes.\n"
        "files_changed: README.md\n"
        "tests_to_run: none"
    )

    assert parsed["patch_draft"].startswith("diff --git")
    assert "+Use MCP repo mapping" in parsed["patch_draft"]
    assert parsed["files_changed"] == ["README.md"]
    assert parsed["tests_to_run"] == ["none"]


def test_parse_handoff_cleans_markdown_fenced_patch_draft():
    parsed = _parse_handoff(
        "status: complete\n"
        "summary: patch ready\n"
        "patch_draft: ** |\n"
        "```diff\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "+Use MCP repo mapping.\n"
        "```\n"
        "files_changed: ** README.md **\n"
        "tests_to_run: ** none **"
    )

    assert parsed["patch_draft"].startswith("--- a/README.md")
    assert "```" not in parsed["patch_draft"]
    assert parsed["files_changed"] == ["README.md"]
    assert parsed["tests_to_run"] == ["none"]


def test_parse_handoff_ignores_markdown_marker_noise_in_structured_fields():
    parsed = _parse_handoff(
        "status: complete\n"
        "summary: useful synthesis\n"
        "ranked_finding: **\n"
        "ranked_finding: apps/agent-runner/src/graph.ts\n"
        "requested_evidence: ** None (documentation-only change).\n"
        "requested_evidence: None required beyond lint verification.\n"
        "requested_evidence: **\n"
        "summary: **\n"
        "evidence_reference: ** `apps/agent-runner/src/graph.ts`\n"
    )

    assert parsed["summary"] == "useful synthesis"
    assert parsed["ranked_findings"] == ["apps/agent-runner/src/graph.ts"]
    assert parsed["requested_evidence"] == []
    assert parsed["evidence_references"] == ["`apps/agent-runner/src/graph.ts`"]


def test_parse_handoff_dedupes_requested_evidence_and_ignores_none_disagreement():
    parsed = _parse_handoff(
        "status: complete\n"
        "summary: review done\n"
        "requested_evidence: ESLint custom rule no-silent-fallback\n"
        "requested_evidence: ESLint custom rule no-silent-fallback\n"
        "disagreement: none\n"
        "disagreement: no disagreement\n"
    )

    assert parsed["requested_evidence"] == ["ESLint custom rule no-silent-fallback"]
    assert parsed["disagreements"] == []


def test_parse_handoff_cleans_inline_bullet_prefixes():
    parsed = _parse_handoff(
        "status: needs_codex_input\n"
        "summary: patch needs evidence\n"
        "requested_evidence: - Documentation reference for steering file discovery.\n"
        "disagreement: - Proposed path conflicts with repo convention.\n"
    )

    assert parsed["requested_evidence"] == [
        "Documentation reference for steering file discovery."
    ]
    assert parsed["disagreements"] == ["Proposed path conflicts with repo convention."]


def test_parse_handoff_extracts_summary_from_embedded_colon_fields():
    parsed = _parse_handoff(
        "status: complete\n"
        "summary: :status: deep_test_strategy_loop_complete "
        ":summary: MCP smoke-test strategy validated "
        ":ranked_finding: 1. missing_fail_loud_guard "
        ":risk: high\n"
    )

    assert parsed["summary"] == "MCP smoke-test strategy validated"


def test_completion_usage_estimates_tokens_when_provider_usage_is_missing():
    usage = CompletionUsage.from_raw(
        None,
        estimated_input_chars=400,
        estimated_output_chars=80,
    )

    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 120


@pytest.mark.asyncio
async def test_specialist_tools_return_usage_contract(tmp_path: Path):
    client = UsageRwthClient(
        [
            ("map: architecture", {"total_tokens": 2}),
            ("status: complete\nsummary: architecture reviewed", {"total_tokens": 3}),
        ]
    )

    result = await make_service(tmp_path, client).deep_architecture_critic(
        question="Find architecture risk",
        context="small repo",
        analysis_depth="fast",
    )

    assert result["status"] == "complete"
    assert result["total_tokens"] == 5
