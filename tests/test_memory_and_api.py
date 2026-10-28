"""记忆、失败转移和 WebUI API。"""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from feiyubot.core.llm import HttpxBackend, LLMError, ProviderRouter, chat_completions_url
from feiyubot.core.models import Settings
from feiyubot.core.pipeline import Incoming
from feiyubot.service import Service
from feiyubot.web.api import install


class ScriptedBackend:
    def __init__(self, *, fail_compress: bool = False):
        self.calls: list[dict] = []
        self.fail_compress = fail_compress

    async def complete(self, *, url, api_key, model, messages, temperature, max_tokens, timeout):
        blob = "\n".join(str(item.get("content") or "") for item in messages)
        self.calls.append({"model": model, "messages": messages, "blob": blob})
        if model == "fail":
            raise LLMError("down", retryable=True)
        system = messages[0]["content"] if messages else ""
        if "对话压缩器" in system:
            if self.fail_compress:
                raise LLMError("compress down", retryable=False)
            bits = []
            if "鱼丸" in blob:
                bits.append("猫叫鱼丸")
            if "Morax" in blob:
                bits.append("用户叫 Morax")
            return "；".join(bits) or "无"
        if "长期记忆管理员" in system:
            return "- 猫叫鱼丸" if "鱼丸" in blob else "- 无"
        last = messages[-1]["content"]
        if "猫" in last and "鱼丸" in blob:
            return "你养的猫叫鱼丸。"
        if "Morax" in last or ("名字" in last and "Morax" in blob):
            return "你叫 Morax。"
        return "我在。"

    async def aclose(self) -> None:
        return None


def _service(tmp_path, backend=None, **settings):
    service = Service.open(tmp_path, admin_password="test", backend=backend or ScriptedBackend())
    if settings:
        current = service.store.get_settings().to_dict()
        current.update(settings)
        service.store.save_settings(Settings.from_dict(current))
    service.store.upsert_provider(
        provider_id=None,
        name="演示",
        base_url="http://127.0.0.1:9/v1",
        api_key="secret-key",
        model="demo",
        enabled=True,
        priority=10,
        timeout_seconds=5,
    )
    return service


async def _say(service: Service, text: str, **kwargs) -> str:
    result = await service.pipeline.handle(
        Incoming(session_id="web:abc123abc123", kind="web", text=text, title="网页", **kwargs)
    )
    assert result.replied, result.reason
    return result.text


def test_urls():
    assert chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/v1/chat/completions"
    assert chat_completions_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/chat/completions"
    assert (
        chat_completions_url("https://open.bigmodel.cn/api/paas/v4")
        == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    assert (
        chat_completions_url("https://example.com/v1/chat/completions")
        == "https://example.com/v1/chat/completions"
    )


def test_short_chat_keeps_every_line(tmp_path):
    async def run():
        backend = ScriptedBackend()
        service = _service(tmp_path, backend)
        await _say(service, "我养的猫叫鱼丸")
        for index in range(8):
            await _say(service, f"第{index}句闲聊")
        answer = await _say(service, "我的猫叫什么？")
        assert answer == "你养的猫叫鱼丸。"
        chat_calls = [call for call in backend.calls if "对话压缩器" not in call["blob"]]
        last = chat_calls[-1]
        assert any("我养的猫叫鱼丸" in item["content"] for item in last["messages"])
        assert service.store.counts()["messages"] > 10

    asyncio.run(run())


def test_old_lines_survive_compression_and_restart(tmp_path):
    async def run():
        backend = ScriptedBackend()
        service = _service(tmp_path, backend, keep_recent=2, compress_after=1, memory_update_every=50)
        await _say(service, "我养的猫叫鱼丸")
        for index in range(6):
            await _say(service, f"闲聊{index}")
        session = service.store.get_session("web:abc123abc123")
        assert session is not None
        assert session.summary_until_id > 0
        assert "鱼丸" in session.summary
        answer = await _say(service, "我的猫叫什么？")
        assert answer == "你养的猫叫鱼丸。"
        last = backend.calls[-1]
        recent = [item["content"] for item in last["messages"][1:]]
        assert not any(item == "我养的猫叫鱼丸" or item.endswith("我养的猫叫鱼丸") for item in recent)
        assert "鱼丸" in last["messages"][0]["content"]
        await service.aclose()

        restarted = ScriptedBackend()
        again = _service(tmp_path, restarted, keep_recent=2, compress_after=1, memory_update_every=50)
        text = await _say(again, "我的猫叫什么？")
        assert text == "你养的猫叫鱼丸。"
        assert again.store.counts()["messages"] > 8

    asyncio.run(run())


def test_compression_fallback_keeps_the_beginning(tmp_path):
    async def run():
        backend = ScriptedBackend(fail_compress=True)
        service = _service(tmp_path, backend, keep_recent=2, compress_after=1, memory_update_every=50)
        await _say(service, "我养的猫叫鱼丸")
        for index in range(6):
            await _say(service, f"闲聊{index}")
        session = service.store.get_session("web:abc123abc123")
        assert session is not None and "鱼丸" in session.summary
        assert await _say(service, "我的猫叫什么？") == "你养的猫叫鱼丸。"

    asyncio.run(run())


def test_group_remembers_messages_it_did_not_answer(tmp_path):
    backend = ScriptedBackend()
    service = _service(tmp_path, backend)

    async def run():
        skipped = await service.pipeline.handle(
            Incoming(
                session_id="group:100",
                kind="group",
                text="我养的猫叫鱼丸",
                sender_name="Morax",
                group_id="100",
                title="测试群",
                addressed=False,
            )
        )
        assert skipped.replied is False
        assert skipped.reason == "wake"
        return await service.pipeline.handle(
            Incoming(
                session_id="group:100",
                kind="group",
                text="我的猫叫什么？",
                sender_name="Morax",
                group_id="100",
                title="测试群",
                addressed=True,
            )
        )

    result = asyncio.run(run())
    assert result.replied is True
    assert result.text == "你养的猫叫鱼丸。"
    stored = service.store.list_messages("group:100", limit=20)
    assert any("我养的猫叫鱼丸" in item.content for item in stored)


def test_explicit_remember_is_pinned(tmp_path):
    async def run():
        service = _service(tmp_path, memory_update_every=1)
        await _say(service, "请记住：我叫 Morax，我养的猫叫鱼丸。")
        notes = service.store.get_session("web:abc123abc123").memory_notes
        assert "Morax" in notes and "鱼丸" in notes

    asyncio.run(run())


def test_provider_failover(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body["model"] == "bad":
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "来自备用模型"}}]})

    service = Service.open(tmp_path, admin_password="test", backend=HttpxBackend(transport=httpx.MockTransport(handler)))
    service.store.upsert_provider(
        provider_id=None, name="主", base_url="https://primary.example/v1", api_key="k",
        model="bad", enabled=True, priority=1, timeout_seconds=5,
    )
    service.store.upsert_provider(
        provider_id=None, name="备", base_url="https://backup.example/v1", api_key="k",
        model="good", enabled=True, priority=2, timeout_seconds=5,
    )
    router = ProviderRouter(service.store, service.backend)
    completion = asyncio.run(router.complete([{"role": "user", "content": "hi"}], pause=0))
    assert completion.text == "来自备用模型"
    assert completion.provider_name == "备"
    health = {item.provider_id: item for item in service.store.list_health()}
    bad = next(item for item in service.store.list_providers() if item.model == "bad")
    assert health[bad.id].ok is False


def test_web_api_round_trip(tmp_path):
    backend = ScriptedBackend()
    service = _service(tmp_path / "api", backend)
    app = FastAPI()
    install(app, service)
    client = TestClient(app)
    assert client.get("/health").json()["ok"] is True
    assert client.get("/").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"password": "test"}).status_code == 200
    created = client.post(
        "/api/providers",
        json={
            "name": "本地",
            "base_url": "http://127.0.0.1:8765/v1",
            "api_key": "super-secret",
            "model": "demo",
            "priority": 1,
        },
    ).json()
    assert "api_key" not in created
    assert created["has_api_key"] is True
    assert "super-secret" not in json.dumps(created)
    first = client.post("/api/chat", json={"content": "我养的猫叫鱼丸"}).json()
    assert first["text"]
    second = client.post(
        "/api/chat", json={"content": "我的猫叫什么？", "session_id": first["session_id"]}
    ).json()
    assert second["text"] == "你养的猫叫鱼丸。"
    history = client.get(f"/api/sessions/{first['session_id']}/messages").json()["messages"]
    assert any("鱼丸" in item["content"] for item in history)
    assert client.post("/api/chat", json={"content": "hi", "session_id": "group:1"}).status_code == 400
    ping = client.post("/api/chat", json={"content": "/ping", "session_id": first["session_id"]}).json()
    assert ping["text"] == "pong"
