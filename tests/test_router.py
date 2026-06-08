import pytest

from codex_rwth_mcp.config import AppConfig, ModelConfig, RouteRule, RwthConfig, ToolConfig
from codex_rwth_mcp.router import ModelRouter, RoutingError


def make_config() -> AppConfig:
    return AppConfig(
        rwth=RwthConfig(base_url="https://api.rwth.example/v1"),
        models={
            "cheap": ModelConfig(id="rwth-cheap", max_input_chars=1_000),
            "long": ModelConfig(id="rwth-long", max_input_chars=100_000),
            "vision": ModelConfig(id="rwth-vision", supports_vision=True),
        },
        tools={
            "summarize_logs": ToolConfig(
                routes=[
                    RouteRule(model="cheap", max_input_chars=1_000),
                    RouteRule(model="long", max_input_chars=100_000),
                ]
            ),
            "analyze_screenshot": ToolConfig(
                routes=[RouteRule(model="vision", requires_vision=True)]
            ),
        },
    )


def test_router_chooses_cheapest_matching_route_for_small_logs():
    decision = ModelRouter(make_config()).route(
        tool_name="summarize_logs",
        input_chars=300,
        needs_vision=False,
    )

    assert decision.route.model == "cheap"
    assert decision.model.id == "rwth-cheap"


def test_router_escalates_large_logs_to_long_context_model():
    decision = ModelRouter(make_config()).route(
        tool_name="summarize_logs",
        input_chars=30_000,
        needs_vision=False,
    )

    assert decision.route.model == "long"
    assert decision.model.id == "rwth-long"


def test_router_requires_vision_capable_route_for_screenshots():
    decision = ModelRouter(make_config()).route(
        tool_name="analyze_screenshot",
        input_chars=250,
        needs_vision=True,
    )

    assert decision.model.id == "rwth-vision"
    assert decision.model.supports_vision is True


def test_router_errors_when_no_route_can_handle_payload():
    with pytest.raises(RoutingError):
        ModelRouter(make_config()).route(
            tool_name="summarize_logs",
            input_chars=200_000,
            needs_vision=False,
        )
