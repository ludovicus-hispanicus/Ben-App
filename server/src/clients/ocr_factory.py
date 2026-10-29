from typing import Optional
from .base_ocr_client import BaseOcrClient
import os
import logging

# Lazy imports - only import clients when needed to avoid requiring all dependencies


def _require_module(module_id: str, label: str):
    """Fail with a clear message when an optional module is not installed."""
    from common.module_status import get_installed_modules
    if not get_installed_modules().get(module_id, False):
        raise ValueError(f"The {label} module is not installed.")


class OCRFactory:
    @staticmethod
    def get_client(provider_name: str, api_key: Optional[str] = None) -> BaseOcrClient:
        original_provider_name = provider_name.strip()
        provider_name = original_provider_name.lower()

        logging.info(f"Initializing OCR client for provider: {provider_name}")

        # Cloud API providers - support provider:submodel format (e.g., gemini_vision:gemini-3-pro)
        # Parse sub-model if present
        sub_model = None
        if ":" in provider_name and not provider_name.startswith("kraken") and not provider_name.startswith("cure") and not provider_name.startswith("qwen_lora") and not provider_name.startswith("vllm"):
            provider_name, sub_model = provider_name.split(":", 1)
            provider_name = provider_name.lower().strip()
            logging.info(f"Parsed sub-model: {sub_model} for provider: {provider_name}")

        if provider_name in ["gemini", "gemini_vision"]:
            from .gemini_client import GeminiOcrClient
            if not api_key:
                raise ValueError("API Key is required for Gemini.")
            return GeminiOcrClient(api_key, model=sub_model)

        elif provider_name in ["openai", "gpt", "gpt4_vision"]:
            from .openai_client import OpenAIOcrClient
            if not api_key:
                raise ValueError("API Key is required for OpenAI.")
            return OpenAIOcrClient(api_key, model=sub_model)

        elif provider_name in ["anthropic", "claude", "claude_vision"]:
            from .anthropic_client import AnthropicOcrClient
            if not api_key:
                raise ValueError("API Key is required for Anthropic.")
            return AnthropicOcrClient(api_key, model=sub_model)

        elif provider_name in ["grok", "xai", "grok_xai"]:
            from .grok_client import GrokOcrClient
            if not api_key:
                raise ValueError("API Key is required for xAI Grok.")
            return GrokOcrClient(api_key, model=sub_model)

        # Kraken models - supports multiple formats:
        # - "kraken_latest", "kraken_dillard" (underscore format from static UI)
        # - "kraken:Base_CUSAS-18_2" (colon format from API for trained models)
        elif provider_name.startswith("kraken"):
            from .kraken_client import KrakenOcrClient
            # Extract model name based on separator
            if ":" in original_provider_name:
                # Format: "kraken:ModelName" (from API/trained models)
                model_name = original_provider_name.split(":", 1)[1]
            elif "_" in provider_name:
                # Format: "kraken_latest" (from static UI)
                model_name = provider_name.split("_", 1)[1]
            else:
                model_name = "latest"
            logging.info(f"Using Kraken OCR with model: {model_name}")
            return KrakenOcrClient(model_name=model_name)

        # CuRe sign classifier - supports "cure", "cure:model_name", "cure_active"
        elif provider_name.startswith("cure"):
            _require_module("cure", "CuRe")
            from .cure_client import CuReOcrClient
            if ":" in original_provider_name:
                model_name = original_provider_name.split(":", 1)[1]
            elif "_" in provider_name:
                model_name = provider_name.split("_", 1)[1]
            else:
                model_name = "active"
            logging.info(f"Using CuRe sign classifier with model: {model_name}")
            return CuReOcrClient(model_name=model_name)

        # Qwen3-VL LoRA adapters - "qwen_lora" or "qwen_lora:adapter_name"
        elif provider_name.startswith("qwen_lora"):
            _require_module("qwen", "Qwen")
            from .qwen_lora_client import QwenLoraOcrClient
            if ":" in original_provider_name:
                adapter_name = original_provider_name.split(":", 1)[1]
            else:
                adapter_name = None
            logging.info(f"Using Qwen3-VL LoRA OCR with adapter: {adapter_name or 'base'}")
            return QwenLoraOcrClient(adapter_name=adapter_name)

        # vLLM server - "vllm" (base model) or "vllm:adapter_name" (LoRA adapter)
        elif provider_name.startswith("vllm"):
            from .vllm_client import VllmOcrClient
            adapter_name = None
            if ":" in original_provider_name:
                adapter_name = original_provider_name.split(":", 1)[1]
            vllm_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
            vllm_model = os.environ.get("VLLM_MODEL_NAME", "Qwen/Qwen3-VL-8B-Instruct")
            logging.info(f"Using vLLM OCR: url={vllm_url}, adapter={adapter_name or 'base'}")
            return VllmOcrClient(
                vllm_base_url=vllm_url,
                model_name=vllm_model,
                adapter_name=adapter_name,
            )

        # Ollama models - check against known models from OLLAMA_MODELS mapping
        else:
            from .ollama_client import OllamaOcrClient, OLLAMA_MODELS
            if provider_name in OLLAMA_MODELS:
                logging.info(f"Using Ollama OCR with model: {provider_name}")
                return OllamaOcrClient(model=provider_name)

            # Dynamic Ollama models (ollama_modelname format from dropdown)
            elif provider_name.startswith("ollama_"):
                # Extract model name: ollama_qwen3-vl:8b -> qwen3-vl:8b
                model_name = provider_name[7:]  # Remove "ollama_" prefix
                logging.info(f"Using dynamic Ollama OCR with model: {model_name}")
                return OllamaOcrClient(model=model_name)

            else:
                raise ValueError(f"Unknown OCR model '{original_provider_name}'.")
