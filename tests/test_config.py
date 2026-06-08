from pathlib import Path

from codex_rwth_mcp.config import load_config


def test_load_config_parses_tool_routes(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
rwth:
  base_url: https://api.rwth.example/v1
  api_key_env: RWTH_OPENAI_API_KEY
models:
  small:
    id: rwth-small
    supports_vision: false
    max_input_chars: 1000
  vision:
    id: rwth-vision
    supports_vision: true
    max_input_chars: 2000
tools:
  summarize_logs:
    routes:
      - model: small
        max_input_chars: 1000
  analyze_screenshot:
    routes:
      - model: vision
        requires_vision: true
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.rwth.base_url == "https://api.rwth.example/v1"
    assert config.models["small"].id == "rwth-small"
    assert config.tools["analyze_screenshot"].routes[0].requires_vision is True


def test_load_config_rejects_unknown_route_model(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
rwth:
  base_url: https://api.rwth.example/v1
  api_key_env: RWTH_OPENAI_API_KEY
models:
  small:
    id: rwth-small
tools:
  summarize_logs:
    routes:
      - model: missing
""",
        encoding="utf-8",
    )

    try:
        load_config(config_file)
    except ValueError as exc:
        assert "unknown model" in str(exc)
    else:
        raise AssertionError("expected config validation to fail")


def test_load_config_prefers_new_config_env_var(monkeypatch, tmp_path: Path):
    old_config = tmp_path / "old.yaml"
    old_config.write_text(
        """
rwth:
  base_url: https://old.example/v1
models:
  small:
    id: old-small
tools:
  summarize_logs:
    routes:
      - model: small
""",
        encoding="utf-8",
    )
    new_config = tmp_path / "new.yaml"
    new_config.write_text(
        """
rwth:
  base_url: https://new.example/v1
models:
  small:
    id: new-small
tools:
  summarize_logs:
    routes:
      - model: small
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_RWTH_MCP_CONFIG", str(old_config))
    monkeypatch.setenv("CODEX_DEEP_LOOP_MCP_CONFIG", str(new_config))

    config = load_config()

    assert config.rwth.base_url == "https://new.example/v1"


def test_load_config_keeps_old_config_env_var_fallback(monkeypatch, tmp_path: Path):
    config_file = tmp_path / "routing.yaml"
    config_file.write_text(
        """
rwth:
  base_url: https://fallback.example/v1
models:
  small:
    id: fallback-small
tools:
  summarize_logs:
    routes:
      - model: small
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("CODEX_DEEP_LOOP_MCP_CONFIG", raising=False)
    monkeypatch.setenv("CODEX_RWTH_MCP_CONFIG", str(config_file))

    config = load_config()

    assert config.rwth.base_url == "https://fallback.example/v1"
