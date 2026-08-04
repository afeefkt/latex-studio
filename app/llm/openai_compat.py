# ── Phase 5: OpenAI-compatible provider base class ──

import asyncio
import json
import os
import random
import ssl
from typing import AsyncIterator, Coroutine, Union

import httpx

try:
    import truststore
    _ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    _ssl_ctx = True  # httpx default

from app.llm.provider import LLMProvider
from app.usage_log import log_usage


class OpenAICompatProvider(LLMProvider):
    base_url: str = ""
    default_model: str = ""
    _override_model: str | None = None

    def __init__(self, model: str | None = None):
        self._override_model = model
        api_key = self._get_api_key()
        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
            verify=_ssl_ctx,
        )

    def _get_api_key(self) -> str:
        raise NotImplementedError

    @property
    def model_name(self) -> str:
        return self._override_model or self.default_model

    def chat(
        self, messages: list[dict], *, stream: bool = False
    ) -> "Union[AsyncIterator[str], Coroutine[None, None, str]]":
        if stream:
            return self._chat_stream(messages)   # async generator — iterable directly
        return self._chat_sync(messages)          # coroutine — must be awaited

    _RETRYABLE_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES: int = 3

    async def _chat_sync(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            resp = await self._client.post("/chat/completions", json=payload)
            if resp.status_code < 400:
                break
            last_exc = ValueError(f"API {resp.status_code}: {resp.text[:400]}")
            if resp.status_code not in self._RETRYABLE_CODES or attempt == self._MAX_RETRIES - 1:
                raise last_exc
            await asyncio.sleep(2 ** attempt + random.uniform(0, 0.5))
        if last_exc is not None:
            raise last_exc
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        log_usage(
            provider=self.provider_name,
            model=self.model_name,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            endpoint="chat",
        )
        return content

    async def _chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
        }
        tokens_in_est = sum(len(m.get("content", "")) // 4 for m in messages)
        tokens_out = 0

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode(errors="replace")[:400]
                raise ValueError(f"API {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        tokens_out += 1
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        log_usage(
            provider=self.provider_name,
            model=self.model_name,
            tokens_in=tokens_in_est,
            tokens_out=tokens_out,
            endpoint="chat",
        )

    async def close(self):
        await self._client.aclose()
