import threading
import time
from types import SimpleNamespace

import pytest

from core.llm import provider
from core.llm.limiter import LLMQueueTimeout, ProviderLimiter
from core.llm.provider import ProviderConfig, call_llm, load_provider_config


def _response(text="ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(provider, "_limiter", ProviderLimiter())


def _cfg(**kw):
    base = dict(provider="openai", model="m", max_concurrent=2)
    base.update(kw)
    return ProviderConfig(**base)


def test_peak_concurrency_never_exceeds_cap(monkeypatch):
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def fake(**kwargs):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return _response()

    monkeypatch.setattr(provider.litellm, "completion", fake)
    cfg = _cfg(max_concurrent=2)
    threads = [
        threading.Thread(target=call_llm, args=([{"role": "user", "content": "x"}], cfg))
        for _ in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["peak"] == 2


def test_queue_wait_timeout_raises(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(
        provider.litellm, "completion", lambda **kw: (release.wait(5), _response())[1]
    )
    monkeypatch.setenv("LLM_QUEUE_TIMEOUT_SECONDS", "0.1")
    cfg = _cfg(max_concurrent=1)
    t = threading.Thread(target=call_llm, args=([{"role": "user", "content": "x"}], cfg))
    t.start()
    time.sleep(0.05)
    try:
        with pytest.raises(LLMQueueTimeout, match="queue wait timed out"):
            call_llm([{"role": "user", "content": "y"}], cfg)
    finally:
        release.set()
        t.join()


def test_slot_released_after_exception(monkeypatch):
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        return _response()

    monkeypatch.setattr(provider.litellm, "completion", fake)
    cfg = _cfg(max_concurrent=1)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        call_llm([{"role": "user", "content": "x"}], cfg)
    assert call_llm([{"role": "user", "content": "x"}], cfg)[0] == "ok"


def test_timed_out_call_keeps_slot_until_worker_finishes(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(
        provider.litellm, "completion", lambda **kw: (release.wait(5), _response())[1]
    )
    monkeypatch.setenv("LITELLM_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setenv("LLM_QUEUE_TIMEOUT_SECONDS", "0.1")
    cfg = _cfg(max_concurrent=1)
    with pytest.raises(RuntimeError, match="timed out after"):
        call_llm([{"role": "user", "content": "x"}], cfg)
    # Worker is still running, so the slot must still be occupied.
    with pytest.raises(LLMQueueTimeout):
        call_llm([{"role": "user", "content": "y"}], cfg)
    release.set()
    time.sleep(0.1)
    monkeypatch.setenv("LITELLM_TIMEOUT_SECONDS", "5")
    assert call_llm([{"role": "user", "content": "z"}], cfg)[0] == "ok"


def test_different_keys_do_not_block_each_other(monkeypatch):
    release = threading.Event()

    def fake(**kwargs):
        if kwargs["model"].endswith("/slow"):
            release.wait(5)
        return _response()

    monkeypatch.setattr(provider.litellm, "completion", fake)
    monkeypatch.setenv("LLM_QUEUE_TIMEOUT_SECONDS", "0.1")
    slow = _cfg(model="slow", max_concurrent=1)
    fast = _cfg(model="fast", max_concurrent=1)
    t = threading.Thread(target=call_llm, args=([{"role": "user", "content": "x"}], slow))
    t.start()
    time.sleep(0.05)
    try:
        assert call_llm([{"role": "user", "content": "y"}], fast)[0] == "ok"
    finally:
        release.set()
        t.join()


def _write_cfg(tmp_path, extra=""):
    p = tmp_path / "providers.yaml"
    p.write_text(f"llm:\n  provider: {extra.split('|')[0] or 'openai'}\n  model: m\n"
                 + (f"  max_concurrent: {extra.split('|')[1]}\n" if "|" in extra else ""))
    return str(p)


def test_config_default_cap_by_provider(tmp_path):
    assert load_provider_config(_write_cfg(tmp_path, "ollama")).max_concurrent is None
    assert provider.effective_max_concurrent(ProviderConfig("ollama", "m")) == 1
    assert provider.effective_max_concurrent(ProviderConfig("openai", "m")) == 4


def test_config_explicit_value(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MAX_CONCURRENT", raising=False)
    assert load_provider_config(_write_cfg(tmp_path, "openai|3")).max_concurrent == 3


def test_env_overrides_yaml_value(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "5")
    assert load_provider_config(_write_cfg(tmp_path, "openai|3")).max_concurrent == 5


def test_blank_env_and_no_yaml_uses_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "")
    assert load_provider_config(_write_cfg(tmp_path, "openai")).max_concurrent is None


@pytest.mark.parametrize("bad", ["0", "-2", "abc"])
def test_config_rejects_invalid_cap(tmp_path, monkeypatch, bad):
    monkeypatch.delenv("LLM_MAX_CONCURRENT", raising=False)
    with pytest.raises(ValueError, match="max_concurrent"):
        load_provider_config(_write_cfg(tmp_path, f"openai|{bad}"))
