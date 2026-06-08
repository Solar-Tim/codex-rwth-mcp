import pytest

from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.router import ModelRouter
from codex_rwth_mcp.tools import ToolService


class FakeRwthClient:
    def __init__(self):
        self.text_calls = []
        self.vision_calls = []

    async def complete_text(self, **kwargs):
        self.text_calls.append(kwargs)
        return "root cause: database timeout"

    async def complete_vision(self, **kwargs):
        self.vision_calls.append(kwargs)
        return "screenshot shows a 500 error"


def make_service() -> ToolService:
    config = AppConfig(
        rwth=RwthConfig(base_url="https://api.rwth.example/v1"),
        models={
            "logs": ModelConfig(id="rwth-logs", max_input_chars=10_000),
            "vision": ModelConfig(id="rwth-vision", supports_vision=True),
        },
        tools={
            "summarize_logs": ToolConfig(
                routes=[RouteRule(model="logs", max_input_chars=10_000)],
                max_output_tokens=700,
                temperature=0.1,
            ),
            "analyze_screenshot": ToolConfig(
                routes=[RouteRule(model="vision", requires_vision=True)],
                max_output_tokens=700,
                temperature=0.0,
            ),
        },
    )
    return ToolService(config=config, router=ModelRouter(config), client=FakeRwthClient())


@pytest.mark.asyncio
async def test_summarize_logs_returns_structured_summary_and_hides_routing():
    service = make_service()

    result = await service.summarize_logs(logs="ERROR connection timed out", context="pytest")

    assert result["summary"] == "root cause: database timeout"
    assert result["tool"] == "summarize_logs"
    assert result["model_id"] == "rwth-logs"
    assert "route" not in result


@pytest.mark.asyncio
async def test_analyze_screenshot_uses_vision_client():
    service = make_service()

    result = await service.analyze_screenshot(
        image_base64="abc123",
        mime_type="image/png",
        question="Why is the UI broken?",
    )

    assert result["summary"] == "screenshot shows a 500 error"
    assert result["tool"] == "analyze_screenshot"
