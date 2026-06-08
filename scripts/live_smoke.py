from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from codex_rwth_mcp.config import load_config
from codex_rwth_mcp.server import create_mcp_server, create_service


DEFAULT_LOGS = "2026-06-08T09:00:00Z ERROR worker failed: missing DATABASE_URL"
DEFAULT_CONTEXT = "Live smoke test. Return a concise diagnosis."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live KiConnect/RWTH MCP smoke test."
    )
    parser.add_argument(
        "--config",
        default="config/routing.kiconnect.yaml",
        help="Routing config to use. Defaults to config/routing.kiconnect.yaml.",
    )
    parser.add_argument("--logs", default=DEFAULT_LOGS)
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    return parser.parse_args()


def require_api_key(env_name: str) -> str:
    api_key = os.getenv(env_name)
    if not api_key:
        raise RuntimeError(f"{env_name} is required")
    return api_key


def fetch_model_ids(*, base_url: str, api_key: str) -> list[str]:
    models_url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        models_url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"GET {models_url} failed with HTTP {exc.code}: {body}") from exc

    return [
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def configured_model_ids(config_path: Path) -> list[str]:
    config = load_config(config_path)
    return sorted({model.id for model in config.models.values()})


async def run_smoke(*, config_path: Path, logs: str, context: str) -> None:
    config = load_config(config_path)
    api_key = require_api_key(config.rwth.api_key_env)
    available_models = fetch_model_ids(base_url=config.rwth.base_url, api_key=api_key)
    expected_models = configured_model_ids(config_path)
    missing_models = [model_id for model_id in expected_models if model_id not in available_models]
    if missing_models:
        raise RuntimeError(
            "Configured model IDs are not available from /models: "
            + ", ".join(missing_models)
        )

    os.environ["CODEX_RWTH_MCP_CONFIG"] = str(config_path)
    create_mcp_server()
    service = create_service()
    result = await service.summarize_logs(logs=logs, context=context)

    print(f"Models endpoint: {config.rwth.base_url.rstrip('/')}/models")
    print(f"Available models: {', '.join(available_models)}")
    print("MCP server constructed.")
    print(f"Tool: {result['tool']}")
    print(f"Model: {result['model_id']}")
    print(f"Summary: {result['summary']}")


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()

    try:
        asyncio.run(run_smoke(config_path=config_path, logs=args.logs, context=args.context))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
