from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig, ModelConfig, RouteRule


class RoutingError(ValueError):
    """Raised when no configured model can handle a tool request."""


@dataclass(frozen=True)
class RoutingDecision:
    tool_name: str
    route: RouteRule
    model: ModelConfig


class ModelRouter:
    def __init__(self, config: AppConfig):
        self._config = config

    def route(
        self,
        *,
        tool_name: str,
        input_chars: int,
        needs_vision: bool,
    ) -> RoutingDecision:
        tool = self._config.tools.get(tool_name)
        if tool is None:
            raise RoutingError(f"no routes configured for tool {tool_name!r}")

        candidates = sorted(
            tool.routes,
            key=lambda route: (
                route.priority,
                self._config.models[route.model].cost_weight,
                route.max_input_chars or self._config.models[route.model].max_input_chars or 10**12,
            ),
        )
        for route in candidates:
            model = self._config.models[route.model]
            if needs_vision and not model.supports_vision:
                continue
            if route.requires_vision and not needs_vision:
                continue
            if input_chars < route.min_input_chars:
                continue
            route_limit = route.max_input_chars or model.max_input_chars
            if route_limit is not None and input_chars > route_limit:
                continue
            return RoutingDecision(tool_name=tool_name, route=route, model=model)

        raise RoutingError(
            f"no route for tool {tool_name!r} can handle {input_chars} chars"
        )
