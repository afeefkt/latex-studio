# ── Phase 5: OpenRouter provider ──

import os

from app.llm.openai_compat import OpenAICompatProvider


class OpenRouterProvider(OpenAICompatProvider):
    base_url = "https://openrouter.ai/api/v1"
    default_model = "meta-llama/llama-3.1-8b-instruct:free"

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def _get_api_key(self) -> str:
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY not set — get a free key at https://openrouter.ai/keys")
        return key

    def _extra_headers(self) -> dict:
        return {
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "LaTeX Studio",
        }
