from types import SimpleNamespace

import litellm
import pytest

from core.llm import provider
from core.llm.provider import (
    LLMQuotaError,
    ProviderConfig,
    UsageMeter,
    call_llm,
    load_fallback_provider_config,
    metered_call,
)

PRIMARY = ProviderConfig(provider="openai", model="primary")
BACKUP = ProviderConfig(provider="openai", model="backup")
MSG = [{"role": "user", "content": "hi"}]


def _response(prompt=7, completion=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def _rate_limited() -> litellm.RateLimitError:
    return litellm.RateLimitError(message="429 slow down", llm_provider="openai", model="primary")


def test_meter_accumulates_tokens(monkeypatch):
    monkeypatch.setattr(provider.litellm, "completion", lambda **kw: _response())
    meter = UsageMeter()
    with metered_call(meter):
        call_llm(MSG, PRIMARY)
        call_llm(MSG, PRIMARY)
    assert meter.tokens == 20


def test_calls_outside_a_meter_context_still_work(monkeypatch):
    monkeypatch.setattr(provider.litellm, "completion", lambda **kw: _response())
    assert call_llm(MSG, PRIMARY) == ("ok", 7, 3)


def test_override_swaps_the_model(monkeypatch):
    seen = []
    monkeypatch.setattr(
        provider.litellm, "completion", lambda **kw: seen.append(kw["model"]) or _response()
    )
    with metered_call(UsageMeter(), override=BACKUP):
        call_llm(MSG, PRIMARY)
    call_llm(MSG, PRIMARY)
    assert seen == ["openai/backup", "openai/primary"]


def test_rate_limit_becomes_quota_error(monkeypatch):
    def boom(**kw):
        raise _rate_limited()

    monkeypatch.setattr(provider.litellm, "completion", boom)
    with pytest.raises(LLMQuotaError) as exc:
        call_llm(MSG, PRIMARY)
    assert isinstance(exc.value, RuntimeError)


def test_other_errors_stay_plain_runtime_errors(monkeypatch):
    def boom(**kw):
        raise ValueError("bad request")

    monkeypatch.setattr(provider.litellm, "completion", boom)
    with pytest.raises(RuntimeError) as exc:
        call_llm(MSG, PRIMARY)
    assert not isinstance(exc.value, LLMQuotaError)


def _yaml(tmp_path, body: str) -> str:
    path = tmp_path / "providers.yaml"
    path.write_text(body)
    return str(path)


def test_fallback_loaded_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("FB_MODEL", "claude-x")
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_MODEL}\n")
    cfg = load_fallback_provider_config(path)
    assert (cfg.provider, cfg.model) == ("anthropic", "claude-x")


def test_fallback_absent_is_none(tmp_path):
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n")
    assert load_fallback_provider_config(path) is None


def test_fallback_with_unset_env_var_is_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FB_NOPE", raising=False)
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_NOPE}\n")
    assert load_fallback_provider_config(path) is None


def test_fallback_with_blank_default_is_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("FB_BLANK", raising=False)
    path = _yaml(tmp_path, "llm:\n  provider: ollama\n  model: m\n  fallback:\n"
                           "    provider: anthropic\n    model: ${FB_BLANK:-}\n")
    assert load_fallback_provider_config(path) is None


def test_missing_config_file_is_none(tmp_path):
    assert load_fallback_provider_config(str(tmp_path / "nope.yaml")) is None
