# ── Phase 5: NVIDIA NIM provider ──

import os

from app.llm.openai_compat import OpenAICompatProvider


class NvidiaProvider(OpenAICompatProvider):
    base_url = "https://integrate.api.nvidia.com/v1"
    default_model = "meta/llama-3.1-70b-instruct"

    @property
    def provider_name(self) -> str:
        return "nvidia"

    def _get_api_key(self) -> str:
        key = os.getenv("NVIDIA_API_KEY", "")
        if not key:
            raise ValueError("NVIDIA_API_KEY not set in .env. Get one at https://integrate.api.nvidia.com")
        return key
