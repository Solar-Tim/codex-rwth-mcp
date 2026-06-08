from pathlib import Path
import subprocess
import sys

from codex_rwth_mcp.config import load_config


ROOT = Path(__file__).resolve().parents[1]


def test_public_repository_hygiene_files_exist():
    required = [
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".gitignore",
        ".env.example",
        ".github/workflows/ci.yml",
        "docs/provider-api.md",
        "docs/roadmap.md",
    ]

    missing = [path for path in required if not (ROOT / path).exists()]

    assert missing == []


def test_default_config_uses_documented_rwth_endpoint():
    config = load_config(ROOT / "config/routing.yaml")

    assert config.rwth.base_url == "https://llm.hpc.itc.rwth-aachen.de"


def test_live_smoke_script_refuses_to_run_without_api_key(monkeypatch):
    config = load_config(ROOT / "config/routing.yaml")
    monkeypatch.delenv(config.rwth.api_key_env, raising=False)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/live_smoke.py"),
            "--config",
            str(ROOT / "config/routing.yaml"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"{config.rwth.api_key_env} is required" in result.stderr
    assert "Bearer" not in result.stderr


def test_public_files_do_not_reference_removed_provider():
    public_files = [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/*.md"),
        *(
            path
            for path in ROOT.glob("config/*.yaml")
            if path.name != "routing.local.yaml"
        ),
        *ROOT.glob("examples/*.toml"),
        ROOT / "scripts/live_smoke.py",
    ]
    provider = "ki" + "connect"
    forbidden = [provider, "ki" + ":connect", "chat." + provider, provider.upper()]

    offenders = []
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden:
            if marker.lower() in lowered:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker}")

    assert offenders == []


def test_public_files_do_not_contain_obvious_secret_placeholders():
    public_files = [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/*.md"),
        *(
            path
            for path in ROOT.glob("config/*.yaml")
            if path.name != "routing.local.yaml"
        ),
        *ROOT.glob("examples/*.toml"),
    ]
    forbidden = ["sk-", "YOUR-API-KEY", "your-openai-key"]

    offenders = []
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker}")

    assert offenders == []
