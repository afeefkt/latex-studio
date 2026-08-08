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
    elif name == "openrouter":
        from app.llm.openrouter import OpenRouterProvider
        return OpenRouterProvider(model=model)
    else:
        raise ValueError(f"Unknown provider: {name}. Try: deepseek, nvidia, ollama, openrouter")


def list_providers() -> list[dict]:
    return [
        {"id": "deepseek", "name": "DeepSeek",
         "available": bool(os.getenv("DEEPSEEK_API_KEY")),
         "models": [
             {"id": "deepseek-chat", "name": "DeepSeek Chat", "free": False},
             {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "free": False},
         ]},
        {"id": "nvidia", "name": "NVIDIA NIM",
         "available": bool(os.getenv("NVIDIA_API_KEY")),
         "models": [
             {"id": "meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B", "free": True},
             {"id": "meta/llama-3.1-70b-instruct", "name": "Llama 3.1 70B", "free": True},
             {"id": "meta/llama-3.2-3b-instruct", "name": "Llama 3.2 3B", "free": True},
             {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "free": True},
             {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B", "free": True},
             {"id": "mistralai/mistral-7b-instruct-v0.3", "name": "Mistral 7B", "free": True},
             {"id": "mistralai/mixtral-8x7b-instruct-v0.1", "name": "Mixtral 8x7B", "free": True},
             {"id": "mistralai/mistral-nemo-12b-instruct", "name": "Mistral Nemo 12B", "free": True},
             {"id": "google/gemma-2-9b-it", "name": "Gemma 2 9B", "free": True},
             {"id": "microsoft/phi-3.5-mini-instruct", "name": "Phi-3.5 Mini", "free": True},
             {"id": "qwen/qwen2.5-72b-instruct", "name": "Qwen 2.5 72B", "free": True},
         ]},
        {"id": "ollama", "name": "Ollama (local)",
         "available": True,
         "models": [
             {"id": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"), "name": "Local model", "free": True},
         ]},
        {"id": "openrouter", "name": "OpenRouter",
         "available": bool(os.getenv("OPENROUTER_API_KEY")),
         "models": [
             {"id": "meta-llama/llama-3.1-8b-instruct:free", "name": "Llama 3.1 8B", "free": True},
             {"id": "meta-llama/llama-3.2-3b-instruct:free", "name": "Llama 3.2 3B", "free": True},
             {"id": "google/gemma-2-9b-it:free", "name": "Gemma 2 9B", "free": True},
             {"id": "mistralai/mistral-7b-instruct:free", "name": "Mistral 7B", "free": True},
             {"id": "microsoft/phi-3.5-mini-128k-instruct:free", "name": "Phi-3.5 Mini 128K", "free": True},
             {"id": "qwen/qwen-2.5-7b-instruct:free", "name": "Qwen 2.5 7B", "free": True},
             {"id": "deepseek/deepseek-chat:free", "name": "DeepSeek Chat", "free": True},
             {"id": "meta-llama/llama-3.1-70b-instruct", "name": "Llama 3.1 70B", "free": False},
             {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku", "free": False},
             {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "free": False},
         ]},
    ]


def list_available_models(provider: str = "") -> list[dict]:
    if not provider:
        return []
    provider = provider.strip().lower()
    for p in list_providers():
        if p["id"] == provider:
            return p.get("models", [])
    return []
