from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class RwthConfig:
    base_url: str
    api_key_env: str = "RWTH_OPENAI_API_KEY"
    organization: Optional[str] = None
    request_timeout_sec: float = 60.0


@dataclass(frozen=True)
class ModelConfig:
    id: str
    supports_vision: bool = False
    max_input_chars: Optional[int] = None
    cost_weight: float = 1.0
    notes: str = ""


@dataclass(frozen=True)
class RouteRule:
    model: str
    max_input_chars: Optional[int] = None
    min_input_chars: int = 0
    requires_vision: bool = False
    priority: int = 100


@dataclass(frozen=True)
class ToolConfig:
    routes: List[RouteRule]
    max_output_tokens: int = 800
    temperature: float = 0.1


@dataclass(frozen=True)
class AppConfig:
    rwth: RwthConfig
    models: Dict[str, ModelConfig]
    tools: Dict[str, ToolConfig]
    server_name: str = "codex-rwth-mcp"


def default_config_path() -> Path:
    configured = os.getenv("CODEX_RWTH_MCP_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return Path("config/routing.yaml")


def load_config(path: Optional[Path] = None) -> AppConfig:
    config_path = path or default_config_path()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    config = _parse_config(raw)
    _validate_config(config)
    return config


def _parse_config(raw: Dict[str, Any]) -> AppConfig:
    rwth_raw = raw.get("rwth", {})
    models_raw = raw.get("models", {})
    tools_raw = raw.get("tools", {})

    if "base_url" not in rwth_raw:
        raise ValueError("rwth.base_url is required")
    if not models_raw:
        raise ValueError("at least one model is required")
    if not tools_raw:
        raise ValueError("at least one tool route is required")

    models = {
        name: ModelConfig(
            id=str(value["id"]),
            supports_vision=bool(value.get("supports_vision", False)),
            max_input_chars=value.get("max_input_chars"),
            cost_weight=float(value.get("cost_weight", 1.0)),
            notes=str(value.get("notes", "")),
        )
        for name, value in models_raw.items()
    }

    tools = {
        name: ToolConfig(
            routes=[
                RouteRule(
                    model=str(route["model"]),
                    max_input_chars=route.get("max_input_chars"),
                    min_input_chars=int(route.get("min_input_chars", 0)),
                    requires_vision=bool(route.get("requires_vision", False)),
                    priority=int(route.get("priority", 100)),
                )
                for route in value.get("routes", [])
            ],
            max_output_tokens=int(value.get("max_output_tokens", 800)),
            temperature=float(value.get("temperature", 0.1)),
        )
        for name, value in tools_raw.items()
    }

    return AppConfig(
        rwth=RwthConfig(
            base_url=str(rwth_raw["base_url"]),
            api_key_env=str(rwth_raw.get("api_key_env", "RWTH_OPENAI_API_KEY")),
            organization=rwth_raw.get("organization"),
            request_timeout_sec=float(rwth_raw.get("request_timeout_sec", 60.0)),
        ),
        models=models,
        tools=tools,
        server_name=str(raw.get("server_name", "codex-rwth-mcp")),
    )


def _validate_config(config: AppConfig) -> None:
    for tool_name, tool in config.tools.items():
        if not tool.routes:
            raise ValueError(f"tool {tool_name!r} must define at least one route")
        for route in tool.routes:
            if route.model not in config.models:
                raise ValueError(
                    f"tool {tool_name!r} references unknown model {route.model!r}"
                )
            model = config.models[route.model]
            if route.requires_vision and not model.supports_vision:
                raise ValueError(
                    f"tool {tool_name!r} route {route.model!r} requires vision but model does not support it"
                )
