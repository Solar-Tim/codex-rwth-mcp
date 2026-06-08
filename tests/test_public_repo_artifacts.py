from pathlib import Path

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
        "docs/rwth-api.md",
        "docs/roadmap.md",
    ]

    missing = [path for path in required if not (ROOT / path).exists()]

    assert missing == []


def test_default_config_uses_documented_rwth_endpoint():
    config = load_config(ROOT / "config/routing.yaml")

    assert config.rwth.base_url == "https://llm.hpc.itc.rwth-aachen.de"


def test_public_files_do_not_contain_obvious_secret_placeholders():
    public_files = [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/*.md"),
        *ROOT.glob("config/*.yaml"),
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
