# ── Phase 5: Ollama (local) provider ──

import os

from app.llm.openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    default_model = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

    @property
    def provider_name(self) -> str:
        return "ollama"

    def _get_api_key(self) -> str:
        return "ollama"
