from __future__ import annotations

from typing import Annotated, Optional

from .config import load_config
from .deep_loop import DeepLoopService
from .router import ModelRouter
from .rwth_client import RwthClient
from .tools import ToolService

INSTRUCTIONS = """Use this server for high-volume, low-value preprocessing only: log clustering,
repository/diff summarization, and screenshot diagnostics. Keep code edits,
architecture decisions, and final reasoning in Codex. Tool routing to RWTH
models is internal and configuration-driven; do not ask for model names. Use
deep-loop tools for large debugging, diff review, and repository mapping tasks;
if they return needs_codex_input, gather the requested evidence and call again."""


def create_service() -> ToolService:
    config = load_config()
    return ToolService(
        config=config,
        router=ModelRouter(config),
        client=RwthClient(config.rwth),
    )


def create_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("mcp package is required to run the MCP server") from exc

    config = load_config()
    service = ToolService(
        config=config,
        router=ModelRouter(config),
        client=RwthClient(config.rwth),
    )
    deep_loop_service = DeepLoopService(
        config=config,
        router=ModelRouter(config),
        client=RwthClient(config.rwth),
    )
    mcp = FastMCP(config.server_name, instructions=INSTRUCTIONS)

    @mcp.tool()
    async def summarize_logs(
        logs: Annotated[str, "Raw logs, traces, terminal output, or CI output to analyze."],
        context: Annotated[
            str,
            "Optional context such as service name, time window, recent change, or failing command.",
        ] = "",
    ) -> dict:
        """Cluster errors, identify likely root causes, and return a compact debugging summary."""
        return await service.summarize_logs(logs=logs, context=context)

    @mcp.tool()
    async def summarize_repo(
        files: Annotated[
            str,
            "Concatenated file excerpts with paths. Include only relevant source, config, and docs.",
        ],
        question: Annotated[
            str,
            "Optional focus question for architecture, flow, ownership, or relevant components.",
        ] = "",
    ) -> dict:
        """Summarize repository architecture, code flow, and relevant files/components."""
        return await service.summarize_repo(files=files, question=question)

    @mcp.tool()
    async def analyze_screenshot(
        image_base64: Annotated[
            str,
            "Base64-encoded screenshot. PNG is preferred for UI, terminal, and browser screenshots.",
        ],
        mime_type: Annotated[str, "Image MIME type such as image/png or image/jpeg."] = "image/png",
        question: Annotated[
            str,
            "Optional diagnostic focus, for example visible error, layout issue, or dashboard anomaly.",
        ] = "",
    ) -> dict:
        """Extract actionable debugging insights from UI, error, terminal, dashboard, or devtools screenshots."""
        return await service.analyze_screenshot(
            image_base64=image_base64,
            mime_type=mime_type,
            question=question,
        )

    @mcp.tool()
    async def summarize_diff(
        diff: Annotated[str, "Unified git diff, PR patch, or copied change set."],
        context: Annotated[
            str,
            "Optional context such as PR title, issue link, release risk, or review focus.",
        ] = "",
    ) -> dict:
        """Summarize changes, risks, affected areas, and review focus from a large diff."""
        return await service.summarize_diff(diff=diff, context=context)

    @mcp.tool()
    async def deep_debug_loop(
        logs: Annotated[str, "Logs, traces, terminal output, or CI output to debug."],
        context: Annotated[str, "Optional service, repo, recent change, or failure context."] = "",
        failing_command: Annotated[str, "Optional command that failed, if known."] = "",
        file_paths: Annotated[
            Optional[list[str]],
            "Optional repo-relative file paths for guarded MCP-side evidence loading.",
        ] = None,
        repo_root: Annotated[
            str,
            "Optional configured repo_roots name for guarded MCP-side evidence loading.",
        ] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect debugging loop and return a Codex handoff or evidence requests."""
        return await deep_loop_service.deep_debug_loop(
            logs=logs,
            context=context,
            failing_command=failing_command,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def deep_diff_review(
        diff: Annotated[str, "Unified diff, PR patch, or copied change set."] = "",
        context: Annotated[str, "Optional PR title, issue link, release risk, or review focus."] = "",
        file_paths: Annotated[
            Optional[list[str]],
            "Optional repo-relative file paths for guarded MCP-side evidence loading.",
        ] = None,
        repo_root: Annotated[
            str,
            "Optional configured repo_roots name for guarded MCP-side evidence loading.",
        ] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect diff-review loop with chunking, merge, and critic phases."""
        return await deep_loop_service.deep_diff_review(
            diff=diff,
            context=context,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def repo_map_loop(
        question: Annotated[str, "Architecture, ownership, flow, or relevant-file question."],
        file_paths: Annotated[
            Optional[list[str]],
            "Optional repo-relative file paths for guarded MCP-side evidence loading.",
        ] = None,
        file_tree: Annotated[str, "Optional file tree or rg --files output."] = "",
        context: Annotated[str, "Optional repo or task context."] = "",
        repo_root: Annotated[
            str,
            "Optional configured repo_roots name for guarded MCP-side evidence loading.",
        ] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect repository-mapping loop over provided tree and guarded file evidence."""
        return await deep_loop_service.repo_map_loop(
            question=question,
            file_paths=file_paths,
            file_tree=file_tree,
            context=context,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def deep_repo_review_loop(
        question: Annotated[str, "Repository review question or focus area."],
        file_tree: Annotated[str, "Optional file tree or rg --files output."] = "",
        context: Annotated[str, "Optional repo or task context."] = "",
        file_paths: Annotated[Optional[list[str]], "Optional guarded file evidence paths."] = None,
        repo_root: Annotated[str, "Optional configured repo_roots name."] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect repository review loop over tree and guarded file evidence."""
        return await deep_loop_service.deep_repo_review_loop(
            question=question,
            file_tree=file_tree,
            context=context,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def deep_test_strategy_loop(
        diff: Annotated[str, "Optional diff or change description."] = "",
        failing_tests: Annotated[str, "Optional failing test output or known failures."] = "",
        context: Annotated[str, "Optional task or repo context."] = "",
        file_paths: Annotated[Optional[list[str]], "Optional guarded file evidence paths."] = None,
        repo_root: Annotated[str, "Optional configured repo_roots name."] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect loop that proposes focused test strategy for a change."""
        return await deep_loop_service.deep_test_strategy_loop(
            diff=diff,
            failing_tests=failing_tests,
            context=context,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def deep_architecture_critic(
        question: Annotated[str, "Architecture risk or design question."],
        context: Annotated[str, "Optional repo or task context."] = "",
        file_paths: Annotated[Optional[list[str]], "Optional guarded file evidence paths."] = None,
        repo_root: Annotated[str, "Optional configured repo_roots name."] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Run a bounded KiConnect architecture critic loop over guarded evidence."""
        return await deep_loop_service.deep_architecture_critic(
            question=question,
            context=context,
            file_paths=file_paths,
            repo_root=repo_root,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def external_repo_scan_loop(
        repo_url: Annotated[str, "Public GitHub repository URL to scan read-only."],
        question: Annotated[str, "Pattern or inspiration question for the external repository."],
        ref: Annotated[str, "Git ref to scan."] = "main",
    ) -> dict:
        """Run a constrained read-only inspiration scan over a public GitHub repository."""
        return await deep_loop_service.external_repo_scan_loop(
            repo_url=repo_url,
            question=question,
            ref=ref,
        )

    @mcp.tool()
    async def coding_task_loop(
        task: Annotated[str, "Specific coding task for a supervised patch-draft proposal."],
        context: Annotated[str, "Optional task or repo context."] = "",
        file_paths: Annotated[Optional[list[str]], "Optional guarded file evidence paths."] = None,
        file_tree: Annotated[str, "Optional file tree or rg --files output."] = "",
        repo_root: Annotated[str, "Optional configured repo_roots name."] = "",
        constraints: Annotated[str, "Optional implementation constraints."] = "",
        test_command: Annotated[str, "Optional test command Codex should run after review."] = "",
        analysis_depth: Annotated[
            str,
            "Optional analysis depth: fast, standard, deep, or exhaustive. Defaults to deep for quality.",
        ] = "deep",
    ) -> dict:
        """Draft a supervised implementation patch for Codex to inspect, apply, or rewrite."""
        return await deep_loop_service.coding_task_loop(
            task=task,
            context=context,
            file_paths=file_paths,
            file_tree=file_tree,
            repo_root=repo_root,
            constraints=constraints,
            test_command=test_command,
            analysis_depth=analysis_depth,
        )

    @mcp.tool()
    async def usage_report(
        days: Annotated[int, "Number of recent days to include."] = 7,
        group_by: Annotated[str, "Grouping mode: tool or model."] = "tool",
    ) -> dict:
        """Report local redaction-safe KiConnect call and token usage metadata."""
        return deep_loop_service.usage_report(days=days, group_by=group_by)

    return mcp


def run() -> None:
    create_mcp_server().run(transport="stdio")
