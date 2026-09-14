import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path("scripts/check_live_e2e.py").resolve()
_SPEC = importlib.util.spec_from_file_location("check_live_e2e", _SCRIPT)
assert _SPEC and _SPEC.loader
check_live_e2e = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check_live_e2e
_SPEC.loader.exec_module(check_live_e2e)


def test_provider_key_mapping():
    assert check_live_e2e._provider_key("anthropic:claude-sonnet-4-6") == "ANTHROPIC_API_KEY"
    assert check_live_e2e._provider_key("openai:gpt-5") == "OPENAI_API_KEY"
    assert check_live_e2e._provider_key("google_genai:gemini-2.5-pro") == "GOOGLE_API_KEY"
    assert check_live_e2e._provider_key("custom:model") == ""


@pytest.mark.asyncio
async def test_live_diagnostics_reports_missing_credentials(monkeypatch):
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "TAVILY_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSCOUT_MODEL", "anthropic:claude-sonnet-4-6")

    result = await check_live_e2e._run_diagnostics("test", 1.0, 1.0)
    assert result["status"] == "blocked_missing_credentials"
    assert set(result["missing"]) == {"ANTHROPIC_API_KEY", "TAVILY_API_KEY"}
    assert result["stages"] == []
