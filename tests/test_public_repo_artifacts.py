from pathlib import Path
import subprocess
import sys

from codex_rwth_mcp.config import load_config


ROOT = Path(__file__).resolve().parents[1]
KICONNECT_MODELS_DOC_URL = "https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models"
RWTH_STUDENT_API_ACCESS_URL = "https://www.itc.rwth-aachen.de/go/id/bndrow?lidx=1#aaaaaaaaabndrpc"


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


def test_kiconnect_config_uses_documented_api_endpoint_and_live_model_ids():
    config = load_config(ROOT / "config/routing.kiconnect.yaml")

    assert config.rwth.base_url == "https://chat.kiconnect.nrw/api/v1"
    assert config.rwth.api_key_env == "KICONNECT_API_KEY"
    assert {model.id for model in config.models.values()} == {
        "gpt-oss-120b",
        "mistralai-mistral-small-4-119b",
    }
    assert config.tools["summarize_logs"].routes[0].model == "cheap_text"


def test_kiconnect_models_reference_is_linked_from_public_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_notes = (ROOT / "docs/rwth-api.md").read_text(encoding="utf-8")

    assert KICONNECT_MODELS_DOC_URL in readme
    assert KICONNECT_MODELS_DOC_URL in api_notes


def test_rwth_student_api_access_announcement_is_linked_from_public_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_notes = (ROOT / "docs/rwth-api.md").read_text(encoding="utf-8")

    assert RWTH_STUDENT_API_ACCESS_URL in readme
    assert RWTH_STUDENT_API_ACCESS_URL in api_notes


def test_live_smoke_script_refuses_to_run_without_api_key(monkeypatch):
    monkeypatch.delenv("KICONNECT_API_KEY", raising=False)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/live_smoke.py"),
            "--config",
            str(ROOT / "config/routing.kiconnect.yaml"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "KICONNECT_API_KEY is required" in result.stderr
    assert "Bearer" not in result.stderr


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
