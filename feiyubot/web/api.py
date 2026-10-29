"""管理 API。网页对话和 QQ 群走同一条 Pipeline。"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from feiyubot.core.llm import LLMError, chat_completions_url
from feiyubot.core.models import Provider, Settings
from feiyubot.core.pipeline import Incoming, load_extensions
from feiyubot.core.store import iso, mask_secret, new_id, public_message, utcnow
from feiyubot.service import Service, read_runtime, write_runtime

UI_DIR = Path(__file__).parent / "ui"
SPA_PAGES = ("/memory", "/providers", "/personas", "/connection", "/settings")
COOKIE = "feiyu_session"
_LOGIN_FAILURES: dict[str, list[float]] = {}
_WEB_SESSION = re.compile(r"web:[a-f0-9]{12}")


def install(app: FastAPI, service: Service) -> None:
    app.include_router(build_router(service))

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "feiyubot"}

    def index() -> FileResponse:
        page = UI_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(503, "界面还没构建。在 frontend 目录执行 npm run build")
        return FileResponse(page)

    app.add_api_route("/", index, methods=["GET"])
    for path in SPA_PAGES:
        app.add_api_route(path, index, methods=["GET"])

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        icon = UI_DIR / "favicon.svg"
        if not icon.is_file():
            raise HTTPException(404, "没有这个文件")
        return FileResponse(icon)

    assets = UI_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")


def build_router(service: Service) -> APIRouter:
    router = APIRouter()
    store = service.store

    def require(request: Request) -> None:
        token = request.cookies.get(COOKIE)
        if not store.admin_session_valid(token):
            raise HTTPException(401, "请先登录")

    @router.post("/api/login")
    def login(payload: dict, request: Request, response: Response) -> dict:
        ip = request.client.host if request.client else "local"
        if _locked(ip):
            raise HTTPException(429, "尝试太多次了，请稍后再试")
        password = str(payload.get("password") or "")
        if not store.verify_password(password):
            _LOGIN_FAILURES.setdefault(ip, []).append(time.time())
            raise HTTPException(401, "密码不对")
        _LOGIN_FAILURES.pop(ip, None)
        token = store.create_admin_session()
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 3600,
            path="/",
        )
        return {"ok": True}

    @router.post("/api/logout")
    def logout(request: Request, response: Response) -> dict:
        store.delete_admin_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/api/me")
    def me(request: Request) -> dict:
        require(request)
        return {"ok": True, "password_is_default": store.verify_password("feiyu-admin")}

    @router.get("/api/status")
    def status(request: Request) -> dict:
        require(request)
        settings = store.get_settings()
        counts = store.counts()
        persona = store.active_persona()
        health = {item.provider_id: item for item in store.list_health()}
        providers = []
        for provider in store.list_providers():
            item = health.get(provider.id)
            providers.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "model": provider.model,
                    "enabled": provider.enabled,
                    "ok": None if item is None else item.ok,
                    "last_error": "" if item is None else item.last_error,
                }
            )
        return {
            "bot_name": settings.bot_name,
            "data_dir": str(service.data_dir),
            "message_count": counts["messages"],
            "session_count": counts["sessions"],
            "active_persona": None if persona is None else {"id": persona.id, "name": persona.name},
            "providers": providers,
            "onebot": _onebot_status(service),
            "password_is_default": store.verify_password("feiyu-admin"),
            "events": store.list_events(20),
        }

    @router.get("/api/settings")
    def get_settings(request: Request) -> dict:
        require(request)
        return store.get_settings().to_dict()

    @router.put("/api/settings")
    def put_settings(payload: dict, request: Request) -> dict:
        require(request)
        merged = store.get_settings().to_dict()
        merged.update(payload or {})
        saved = store.save_settings(Settings.from_dict(merged))
        store.add_event("info", "更新了机器人设置")
        return saved.to_dict()

    @router.post("/api/password")
    def change_password(payload: dict, request: Request, response: Response) -> dict:
        require(request)
        old = str(payload.get("old") or "")
        new = str(payload.get("new") or "")
        if not store.verify_password(old):
            raise HTTPException(400, "原密码不对")
        try:
            store.set_password(new)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        token = store.create_admin_session()
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600, path="/")
        return {"ok": True}

    @router.get("/api/providers")
    def list_providers(request: Request) -> list[dict]:
        require(request)
        health = {item.provider_id: item for item in store.list_health()}
        return [_public_provider(item, health.get(item.id)) for item in store.list_providers()]

    @router.post("/api/providers")
    def create_provider(payload: dict, request: Request) -> dict:
        require(request)
        provider = _save_provider(store, None, payload)
        store.add_event("info", f"添加了模型提供商 {provider.name}")
        return _public_provider(provider, None)

    @router.put("/api/providers/{provider_id}")
    def update_provider(provider_id: str, payload: dict, request: Request) -> dict:
        require(request)
        if store.get_provider(provider_id) is None:
            raise HTTPException(404, "没有这个提供商")
        provider = _save_provider(store, provider_id, payload)
        return _public_provider(provider, None)

    @router.delete("/api/providers/{provider_id}")
    def delete_provider(provider_id: str, request: Request) -> dict:
        require(request)
        if not store.delete_provider(provider_id):
            raise HTTPException(404, "没有这个提供商")
        return {"ok": True}

    @router.post("/api/providers/{provider_id}/test")
    async def test_provider(provider_id: str, request: Request) -> dict:
        require(request)
        provider = store.get_provider(provider_id)
        if provider is None:
            raise HTTPException(404, "没有这个提供商")
        return await _probe(service, provider, remember=True)

    @router.post("/api/provider-tests")
    async def test_draft(payload: dict, request: Request) -> dict:
        require(request)
        try:
            base_url = str(payload.get("base_url") or "").strip()
            chat_completions_url(base_url)
            provider = Provider(
                id="draft",
                name=str(payload.get("name") or "未保存"),
                base_url=base_url,
                api_key=str(payload.get("api_key") or ""),
                model=str(payload.get("model") or "").strip(),
                enabled=True,
                priority=100,
                timeout_seconds=float(payload.get("timeout_seconds") or 60),
                created_at=iso(),
                updated_at=iso(),
            )
        except (LLMError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if not provider.model:
            raise HTTPException(400, "请填写模型名")
        return await _probe(service, provider, remember=False)

    @router.get("/api/personas")
    def list_personas(request: Request) -> list[dict]:
        require(request)
        return [_public_persona(item) for item in store.list_personas()]

    @router.post("/api/personas")
    def create_persona(payload: dict, request: Request) -> dict:
        require(request)
        try:
            persona = store.upsert_persona(
                persona_id=None,
                name=str(payload.get("name") or ""),
                prompt=str(payload.get("prompt") or ""),
                activate=bool(payload.get("activate")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return _public_persona(persona)

    @router.put("/api/personas/{persona_id}")
    def update_persona(persona_id: str, payload: dict, request: Request) -> dict:
        require(request)
        if store.get_persona(persona_id) is None:
            raise HTTPException(404, "没有这个人格")
        try:
            persona = store.upsert_persona(
                persona_id=persona_id,
                name=str(payload.get("name") or ""),
                prompt=str(payload.get("prompt") or ""),
                activate=bool(payload.get("activate")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return _public_persona(persona)

    @router.post("/api/personas/{persona_id}/activate")
    def activate_persona(persona_id: str, request: Request) -> dict:
        require(request)
        persona = store.activate_persona(persona_id)
        if persona is None:
            raise HTTPException(404, "没有这个人格")
        return _public_persona(persona)

    @router.delete("/api/personas/{persona_id}")
    def delete_persona(persona_id: str, request: Request) -> dict:
        require(request)
        try:
            deleted = store.delete_persona(persona_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not deleted:
            raise HTTPException(404, "没有这个人格")
        return {"ok": True}

    @router.get("/api/sessions")
    def list_sessions(request: Request, kind: str | None = None) -> list[dict]:
        require(request)
        if kind not in {None, "group", "web"}:
            raise HTTPException(400, "kind 只能是 group 或 web")
        return store.list_sessions(kind)

    @router.get("/api/sessions/{session_id}")
    def get_session(session_id: str, request: Request) -> dict:
        require(request)
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(404, "没有这个会话")
        from feiyubot.core.store import _public_session

        data = _public_session(session)
        data["messages"] = [public_message(item) for item in store.list_messages(session_id, limit=200)]
        return data

    @router.put("/api/sessions/{session_id}")
    def update_session(session_id: str, payload: dict, request: Request) -> dict:
        require(request)
        fields = {}
        for key in ("title", "persona_id", "wake_mode", "enabled", "summary", "memory_notes", "knowledge"):
            if key in payload:
                fields[key] = payload[key]
        try:
            session = store.update_session(session_id, **fields)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if session is None:
            raise HTTPException(404, "没有这个会话")
        from feiyubot.core.store import _public_session

        return _public_session(session)

    @router.post("/api/sessions/{session_id}/clear")
    def clear_session(session_id: str, request: Request) -> dict:
        require(request)
        if not store.clear_conversation(session_id):
            raise HTTPException(404, "没有这个会话")
        store.add_event("info", f"清空了会话 {session_id} 的上下文")
        return {"ok": True}

    @router.post("/api/sessions/{session_id}/compress")
    async def compress_session(session_id: str, request: Request) -> dict:
        require(request)
        session = await service.pipeline.compress_session(session_id)
        if session is None:
            raise HTTPException(404, "没有这个会话")
        from feiyubot.core.store import _public_session

        return _public_session(session)

    @router.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str, request: Request) -> dict:
        require(request)
        if not store.delete_session(session_id):
            raise HTTPException(404, "没有这个会话")
        return {"ok": True}

    @router.get("/api/sessions/{session_id}/messages")
    def list_messages(session_id: str, request: Request, before_id: int | None = None, limit: int = 100) -> dict:
        require(request)
        if store.get_session(session_id) is None:
            raise HTTPException(404, "没有这个会话")
        messages = store.list_messages(session_id, limit=limit, before_id=before_id)
        return {"messages": [public_message(item) for item in messages]}

    @router.post("/api/chat")
    async def chat(payload: dict, request: Request) -> dict:
        require(request)
        content = str(payload.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "请输入内容")
        session_id = payload.get("session_id")
        if session_id:
            session_id = str(session_id)
            if not _WEB_SESSION.fullmatch(session_id):
                raise HTTPException(400, "网页对话不能写入群会话")
            if store.get_session(session_id) is None:
                raise HTTPException(404, "没有这个网页会话")
        else:
            session_id = "web:" + new_id()
        result = await service.pipeline.handle(
            Incoming(
                session_id=session_id,
                kind="web",
                text=content,
                sender_name="你",
                title=str(payload.get("title") or "网页对话"),
            )
        )
        return {
            "session_id": result.session_id,
            "replied": result.replied,
            "text": result.text,
            "reason": result.reason,
            "provider": result.provider,
        }

    @router.get("/api/extensions")
    def extensions(request: Request) -> list[dict]:
        require(request)
        disabled = set(store.get_settings().disabled_extensions)
        return [
            {"name": item.name, "doc": item.doc, "enabled": item.name not in disabled}
            for item in load_extensions()
        ]

    @router.get("/api/onebot")
    def get_onebot(request: Request) -> dict:
        require(request)
        return _onebot_status(service)

    @router.put("/api/onebot")
    def put_onebot(payload: dict, request: Request) -> dict:
        require(request)
        updates: dict[str, str | None] = {}
        if "access_token" in payload:
            token = payload.get("access_token")
            updates["ONEBOT_V11_ACCESS_TOKEN"] = None if token in (None, "") else str(token).strip()
        if "ws_urls" in payload:
            urls = payload.get("ws_urls") or []
            if isinstance(urls, str):
                urls = [part.strip() for part in urls.replace("，", ",").split(",") if part.strip()]
            if not isinstance(urls, list):
                raise HTTPException(400, "正向 WS 地址需要是列表")
            cleaned = []
            for url in urls:
                text = str(url).strip()
                if not text:
                    continue
                if not (text.startswith("ws://") or text.startswith("wss://")):
                    raise HTTPException(400, "正向连接必须以 ws:// 或 wss:// 开头")
                cleaned.append(text)
            if cleaned:
                import json

                updates["ONEBOT_V11_WS_URLS"] = json.dumps(cleaned, ensure_ascii=False)
            else:
                updates["ONEBOT_V11_WS_URLS"] = None
        try:
            write_runtime(service.data_dir, updates)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.add_event("info", "更新了 OneBot 连接配置，重启后生效")
        return {"ok": True, "restart_required": True, **_onebot_status(service)}

    @router.get("/api/events")
    def events(request: Request) -> list[dict]:
        require(request)
        return store.list_events(50)

    return router


def _save_provider(store, provider_id: str | None, payload: dict):
    try:
        priority = int(payload.get("priority") if payload.get("priority") is not None else 100)
        timeout = float(payload.get("timeout_seconds") if payload.get("timeout_seconds") is not None else 60)
        return store.upsert_provider(
            provider_id=provider_id,
            name=str(payload.get("name") or ""),
            base_url=str(payload.get("base_url") or ""),
            api_key=str(payload.get("api_key")) if "api_key" in payload else None,
            model=str(payload.get("model") or ""),
            enabled=bool(payload.get("enabled", True)),
            priority=priority,
            timeout_seconds=timeout,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _public_provider(provider: Provider, health) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key_mask": mask_secret(provider.api_key),
        "has_api_key": bool(provider.api_key),
        "model": provider.model,
        "enabled": provider.enabled,
        "priority": provider.priority,
        "timeout_seconds": provider.timeout_seconds,
        "ok": None if health is None else health.ok,
        "last_error": "" if health is None else health.last_error,
        "cooldown_until": None if health is None else health.cooldown_until,
        "updated_at": provider.updated_at,
    }


def _public_persona(persona) -> dict:
    return {
        "id": persona.id,
        "name": persona.name,
        "prompt": persona.prompt,
        "is_active": persona.is_active,
        "updated_at": persona.updated_at,
    }


async def _probe(service: Service, provider: Provider, *, remember: bool) -> dict:
    started = time.perf_counter()
    try:
        text = await service.backend.complete(
            url=chat_completions_url(provider.base_url),
            api_key=provider.api_key,
            model=provider.model,
            messages=[
                {"role": "system", "content": "用不超过 20 个字回答。"},
                {"role": "user", "content": "请只回复：在。"},
            ],
            temperature=0,
            max_tokens=32,
            timeout=provider.timeout_seconds,
        )
    except LLMError as exc:
        if remember:
            service.store.mark_provider_failed(provider.id, str(exc))
            service.store.add_event("error", f"测试 {provider.name} 失败: {exc}")
        return {"ok": False, "error": str(exc), "latency_ms": int((time.perf_counter() - started) * 1000)}
    if remember:
        service.store.mark_provider_ok(provider.id)
        service.store.add_event("info", f"测试 {provider.name} 成功")
    return {
        "ok": True,
        "reply": text[:200],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def _onebot_status(service: Service) -> dict:
    connected = []
    try:
        import nonebot

        bots = nonebot.get_bots()
    except Exception:
        bots = {}
    for bot_id, bot in bots.items():
        connected.append({"id": str(bot_id), "adapter": type(bot).__name__})
    saved = read_runtime(service.data_dir)
    running_token = os.environ.get("ONEBOT_V11_ACCESS_TOKEN") or ""
    saved_token = saved.get("ONEBOT_V11_ACCESS_TOKEN") or ""
    return {
        "connected": connected,
        "reverse_ws_path": "/onebot/v11/ws",
        "http_path": "/onebot/v11/http",
        "token_configured": bool(running_token),
        "saved_token_configured": bool(saved_token),
        "saved_ws_urls": saved.get("ONEBOT_V11_WS_URLS") or "",
        "restart_required": bool(saved_token) and saved_token != running_token,
        "server_time": iso(utcnow()),
    }


def _locked(ip: str) -> bool:
    now = time.time()
    recent = [item for item in _LOGIN_FAILURES.get(ip, []) if now - item < 60]
    _LOGIN_FAILURES[ip] = recent
    return len(recent) >= 8
