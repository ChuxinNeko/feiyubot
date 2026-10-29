"""OpenAI 兼容接口与多提供商失败转移。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from feiyubot.core.models import Provider
from feiyubot.core.store import Store, iso


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class NoProviderError(LLMError):
    def __init__(self) -> None:
        super().__init__("还没有可用的模型提供商", retryable=False)


class AllProvidersFailed(LLMError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors) if errors else "全部模型提供商都失败了", retryable=False)


def chat_completions_url(base_url: str) -> str:
    """把用户填写的 API 根地址补成 chat/completions。

    已带版本路径的地址（/v1、/v4 等）只追加 /chat/completions，避免再套一层 /v1。
    """

    url = base_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMError("API 地址必须是 http 或 https", retryable=False)
    if url.endswith("/chat/completions"):
        return url
    path = parsed.path.rstrip("/")
    if re.search(r"/v\d+[a-zA-Z0-9]*$", path):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


class ChatBackend(Protocol):
    async def complete(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str: ...

    async def aclose(self) -> None: ...


class HttpxBackend:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport, follow_redirects=False)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            response = await self._http().post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise LLMError("请求超时", retryable=True) from exc
        except httpx.TransportError as exc:
            raise LLMError(f"网络错误: {exc.__class__.__name__}", retryable=True) from exc
        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
            raise LLMError(
                f"HTTP {response.status_code}: {_error_text(response)}",
                retryable=retryable,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("模型返回的不是 JSON", retryable=True) from exc
        return _message_text(body)


@dataclass
class Completion:
    text: str
    provider_id: str
    provider_name: str


class ProviderRouter:
    def __init__(self, store: Store, backend: ChatBackend):
        self.store = store
        self.backend = backend

    async def complete(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        purpose: str = "chat",
        pause: float = 0.05,
    ) -> Completion:
        settings = self.store.get_settings()
        providers = self._ordered_providers()
        if not providers:
            raise NoProviderError()
        temperature = settings.temperature if temperature is None else temperature
        max_tokens = settings.max_tokens if max_tokens is None else max_tokens
        errors: list[str] = []
        for provider in providers:
            for attempt in range(1, settings.max_retries + 1):
                try:
                    text = await self.backend.complete(
                        url=chat_completions_url(provider.base_url),
                        api_key=provider.api_key,
                        model=provider.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=provider.timeout_seconds or settings.request_timeout,
                    )
                except LLMError as exc:
                    self.store.mark_provider_failed(provider.id, str(exc))
                    self.store.add_event(
                        "error",
                        f"{provider.name} {purpose} 失败（第 {attempt} 次）: {exc}",
                    )
                    if exc.retryable and attempt < settings.max_retries:
                        await asyncio.sleep(pause * attempt)
                        continue
                    errors.append(f"{provider.name}: {exc}")
                    break
                else:
                    self.store.mark_provider_ok(provider.id)
                    return Completion(text=text, provider_id=provider.id, provider_name=provider.name)
        raise AllProvidersFailed(errors)

    def _ordered_providers(self) -> list[Provider]:
        providers = [item for item in self.store.list_providers() if item.enabled]
        health = {item.provider_id: item for item in self.store.list_health()}
        now = iso()

        def cooling(provider: Provider) -> bool:
            item = health.get(provider.id)
            return bool(item and item.cooldown_until and item.cooldown_until > now and item.consecutive_failures >= 3)

        ready = [item for item in providers if not cooling(item)]
        later = [item for item in providers if cooling(item)]
        return ready + later


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:180]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:180]
    if isinstance(error, str):
        return error[:180]
    return (response.text or "").strip()[:180]


def _message_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise LLMError("模型返回的结构无法识别", retryable=True)
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices, list):
        raise LLMError("模型没有返回 choices", retryable=True)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
        text = "\n".join(part.strip() for part in parts if part.strip())
    else:
        text = ""
    if not text:
        raise LLMError("模型返回了空内容", retryable=True)
    return text
