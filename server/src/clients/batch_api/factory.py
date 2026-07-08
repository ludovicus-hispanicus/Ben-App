"""Factory mapping a Batch Recognition model name to a provider batch adapter.

Accepts the same ``provider`` / ``provider:sub_model`` strings the live
``OCRFactory`` uses, so the UI's existing model dropdown drives both paths.
Only the four cloud providers with a real async Batch API are supported;
everything else raises (the UI disables the Batch toggle for those).
"""

from typing import Optional

from .base import ProviderBatchAdapter

# provider aliases -> canonical key
_ALIASES = {
    "gemini": "gemini", "gemini_vision": "gemini",
    "anthropic": "anthropic", "claude": "anthropic", "claude_vision": "anthropic",
    "openai": "openai", "gpt": "openai", "gpt4_vision": "openai",
    "grok": "grok", "xai": "grok", "grok_xai": "grok",
}

BATCH_API_PROVIDERS = ("gemini", "anthropic", "openai", "grok")


def supports_batch_api(model: str) -> bool:
    """True if *model* (possibly ``provider:sub_model``) maps to a batch provider."""
    if not model:
        return False
    provider = model.split(":", 1)[0].strip().lower()
    return provider in _ALIASES


def get_batch_adapter(model: str, api_key: Optional[str]) -> ProviderBatchAdapter:
    provider_raw = model.split(":", 1)[0].strip().lower()
    sub_model = model.split(":", 1)[1].strip() if ":" in model else None

    key = _ALIASES.get(provider_raw)
    if key is None:
        raise ValueError(
            f"Model '{model}' does not support async Batch API. "
            f"Supported: {', '.join(BATCH_API_PROVIDERS)}."
        )

    if key == "gemini":
        from .gemini import GeminiBatchAdapter
        return GeminiBatchAdapter(api_key, model=sub_model)
    if key == "anthropic":
        from .anthropic import AnthropicBatchAdapter
        return AnthropicBatchAdapter(api_key, model=sub_model)
    if key == "openai":
        from .openai_compat import OpenAIBatchAdapter
        return OpenAIBatchAdapter(api_key, model=sub_model)
    if key == "grok":
        from .openai_compat import GrokBatchAdapter
        return GrokBatchAdapter(api_key, model=sub_model)

    raise ValueError(f"Unhandled batch provider '{key}'")
