import pytest

from codex_rwth_mcp.server import create_mcp_server


@pytest.mark.asyncio
async def test_mcp_server_registers_deep_loop_tools(monkeypatch, tmp_path):
    config_file = tmp_path / "routing.yaml"
    config_file.write_text(
        """
server_name: test-server
rwth:
  base_url: https://api.example/v1
  api_key_env: TEST_KEY
models:
  text:
    id: rwth-text
    max_input_chars: 100000
tools:
  summarize_logs:
    routes:
      - model: text
  summarize_repo:
    routes:
      - model: text
  summarize_diff:
    routes:
      - model: text
  analyze_screenshot:
    routes:
      - model: text
  deep_debug_loop:
    routes:
      - model: text
  deep_diff_review:
    routes:
      - model: text
  repo_map_loop:
    routes:
      - model: text
  deep_repo_review_loop:
    routes:
      - model: text
  deep_test_strategy_loop:
    routes:
      - model: text
  deep_architecture_critic:
    routes:
      - model: text
  external_repo_scan_loop:
    routes:
      - model: text
  coding_task_loop:
    routes:
      - model: text
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_DEEP_LOOP_MCP_CONFIG", str(config_file))
    monkeypatch.setenv("TEST_KEY", "test-key")

    mcp = create_mcp_server()
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert {
        "deep_debug_loop",
        "deep_diff_review",
        "repo_map_loop",
        "deep_repo_review_loop",
        "deep_test_strategy_loop",
        "deep_architecture_critic",
        "external_repo_scan_loop",
        "coding_task_loop",
        "usage_report",
    } <= names
