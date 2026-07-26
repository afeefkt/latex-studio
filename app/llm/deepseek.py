# ── Phase 5: DeepSeek provider ──

import os

from app.llm.openai_compat import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def _get_api_key(self) -> str:
        key = os.getenv("DEEPSEEK_API_KEY", "")
        if not key:
            raise ValueError("DEEPSEEK_API_KEY not set in .env. Get one at https://platform.deepseek.com")
        return key
