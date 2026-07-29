# ── Phase 5: LLM Provider — ABC + factory ──

import os
from abc import ABC, abstractmethod
from typing import AsyncIterator

from dotenv import load_dotenv

from app.paths import DATA_ROOT

load_dotenv(DATA_ROOT / ".env")
load_dotenv()  # fallback to cwd for dev convenience


class LLMProvider(ABC):
    @abstractmethod
    def chat(
        self, messages: list[dict], *, stream: bool = False
    ) -> "AsyncIterator[str]":
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


def get_provider(name: str | None = None, model: str | None = None) -> "LLMProvider":
    name = (name or os.getenv("LLM_PROVIDER", "deepseek")).strip().lower()

    if name == "deepseek":
        from app.llm.deepseek import DeepSeekProvider
        return DeepSeekProvider(model=model)
    elif name in ("nvidia", "nim"):
        from app.llm.nvidia import NvidiaProvider
        return NvidiaProvider(model=model)
    elif name == "ollama":
        from app.llm.ollama import OllamaProvider
        return OllamaProvider(model=model)
    else:
        raise ValueError(f"Unknown provider: {name}. Try: deepseek, nvidia, ollama")


def list_providers() -> list[dict]:
    return [
        {"id": "deepseek", "name": "DeepSeek",
         "available": bool(os.getenv("DEEPSEEK_API_KEY")),
         "models": ["deepseek-chat", "deepseek-reasoner"]},
        {"id": "nvidia", "name": "NVIDIA NIM",
         "available": bool(os.getenv("NVIDIA_API_KEY")),
         "models": [
             "meta/llama-3.1-70b-instruct",
             "meta/llama-3.1-8b-instruct",
             "deepseek-ai/deepseek-r1",
             "mistralai/mixtral-8x22b-instruct-v0.1",
         ]},
        {"id": "ollama", "name": "Ollama (local)",
         "available": True,
         "models": [os.getenv("OLLAMA_MODEL", "qwen2.5:14b")]},
    ]


def list_available_models(provider: str = "") -> list[dict]:
    if not provider:
        return []
    provider = provider.strip().lower()
    for p in list_providers():
        if p["id"] == provider:
            return [{"id": m, "name": m} for m in p.get("models", [])]
    return []
