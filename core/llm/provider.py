import os
import re
from dataclasses import dataclass
from typing import Optional

import litellm
import yaml


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


def _resolve_env_vars(value: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), value)


def load_provider_config(config_path: str = "config/providers.yaml") -> ProviderConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    llm = raw.get("llm", {})

    provider = llm.get("provider")
    model = llm.get("model")

    if not provider:
        raise ValueError("Missing required field: provider")
    if not model:
        raise ValueError("Missing required field: model")

    api_key = llm.get("api_key")
    base_url = llm.get("base_url")

    return ProviderConfig(
        provider=_resolve_env_vars(provider),
        model=_resolve_env_vars(model),
        api_key=_resolve_env_vars(api_key) if api_key else None,
        base_url=_resolve_env_vars(base_url) if base_url else None,
    )


def call_llm(
    messages: list[dict],
    config: ProviderConfig,
    system_prompt: str = "",
) -> tuple[str, int, int]:
    messages = list(messages)

    use_system_role = True
    if (
        config.provider == "anthropic"
        and config.base_url
        and "api.anthropic.com" not in config.base_url
    ):
        # LM Studio Anthropic-compatible endpoints may use model templates that
        # reject explicit `system` role messages.
        use_system_role = False

    if system_prompt:
        if use_system_role:
            messages = [{"role": "system", "content": system_prompt}] + messages
        else:
            instruction_prefix = f"System instructions:\n{system_prompt}\n\n"
            if (
                messages
                and messages[0].get("role") == "user"
                and isinstance(messages[0].get("content"), str)
            ):
                first = dict(messages[0])
                first["content"] = instruction_prefix + first["content"]
                messages[0] = first
            else:
                messages = [{"role": "user", "content": instruction_prefix}] + messages

    kwargs = {
        "model": f"{config.provider}/{config.model}",
        "messages": messages,
    }
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    try:
        response = litellm.completion(**kwargs)
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e

    text = response.choices[0].message.content
    prompt_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens

    return text, prompt_tokens, output_tokens
