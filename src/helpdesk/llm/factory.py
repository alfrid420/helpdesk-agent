from __future__ import annotations

import os

from ..config import ConfigError, Settings
from .base import LLMClient


def create_llm(settings: Settings) -> LLMClient:
    """Build the configured LLM client. Raise ConfigError with a clear message if misconfigured."""
    if settings.llm_provider == "ollama":
        from .ollama_client import OllamaClient
        model = os.environ.get("OLLAMA_MODEL", "mistral")
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return OllamaClient(model=model, base_url=base_url)

    if settings.llm_provider == "anthropic":
        from .anthropic_client import AnthropicClient
        if not settings.anthropic_api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set.\n"
                "  Tip: set LLM_PROVIDER=ollama in .env to use a free local model instead.\n"
                "       Run: ollama pull mistral  then  ollama serve"
            )
        return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)

    raise ConfigError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'.\n"
        "  Supported: ollama (free, local) or anthropic (needs API key)."
    )
