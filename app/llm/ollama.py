# ── Phase 5: Ollama (local) provider ──

import os

from app.llm.openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    # Read dynamically in __init__ so runtime saves via POST /api/settings/apikey take effect

    def __init__(self, model: str | None = None):
        raw = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        # Auto-fix: user may paste just http://localhost:11434 without /v1
        if not raw.endswith("/v1"):
            raw = raw + "/v1"
        self.base_url = raw
        self.default_model = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
        super().__init__(model)

    @property
    def provider_name(self) -> str:
        return "ollama"

    def _get_api_key(self) -> str:
        return "ollama"
