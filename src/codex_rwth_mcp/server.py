from __future__ import annotations

from typing import Annotated, Optional

from .config import load_config
from .router import ModelRouter
from .rwth_client import RwthClient
from .tools import ToolService

INSTRUCTIONS = """Use this server for high-volume, low-value preprocessing only: log clustering,
repository/diff summarization, and screenshot diagnostics. Keep code edits,
architecture decisions, and final reasoning in Codex. Tool routing to RWTH
models is internal and configuration-driven; do not ask for model names."""


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

    return mcp


def run() -> None:
    create_mcp_server().run(transport="stdio")
