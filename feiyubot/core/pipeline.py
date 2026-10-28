"""把一条群消息或网页消息变成回复，并维护持久上下文。"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from dataclasses import dataclass

from feiyubot.core.llm import AllProvidersFailed, LLMError, NoProviderError, ProviderRouter
from feiyubot.core.memory import (
    HELP_TEXT,
    admission,
    build_messages,
    compression_prompt,
    estimate_messages,
    is_command,
    local_summary,
    memory_prompt,
    parse_command,
    pin_explicit_memory,
    render_system,
    wants_reply,
)
from feiyubot.core.models import ChatMessage, Persona, Session, TurnResult
from feiyubot.core.store import Store, iso, utcnow

logger = logging.getLogger("feiyubot")


@dataclass
class Incoming:
    session_id: str
    kind: str
    text: str
    sender_id: str | None = None
    sender_name: str | None = None
    title: str | None = None
    group_id: str | None = None
    addressed: bool = False


@dataclass
class _Extension:
    name: str
    module: object
    doc: str


_EXTENSIONS: list[_Extension] | None = None


def load_extensions() -> list[_Extension]:
    global _EXTENSIONS
    if _EXTENSIONS is not None:
        return _EXTENSIONS
    import feiyubot.extensions as package

    found: list[_Extension] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"feiyubot.extensions.{module_info.name}")
        except Exception:
            logger.exception("扩展 %s 加载失败", module_info.name)
            continue
        if not hasattr(module, "on_message"):
            continue
        found.append(
            _Extension(
                name=module_info.name,
                module=module,
                doc=(module.__doc__ or "").strip().splitlines()[0] if module.__doc__ else "",
            )
        )
    _EXTENSIONS = found
    return found


class Pipeline:
    def __init__(self, store: Store, router: ProviderRouter):
        self.store = store
        self.router = router
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def handle(self, incoming: Incoming) -> TurnResult:
        async with self._lock(incoming.session_id):
            return await self._handle(incoming)

    async def compress_session(self, session_id: str) -> Session | None:
        async with self._lock(session_id):
            session = self.store.get_session(session_id)
            if session is None:
                return None
            raw = self.store.messages_after(session_id, session.summary_until_id)
            settings = self.store.get_settings()
            keep = min(settings.keep_recent, max(1, len(raw) // 2)) if len(raw) > 2 else len(raw)
            if len(raw) <= keep:
                return session
            await self._compress(session, raw[: len(raw) - keep])
            return self.store.get_session(session_id)

    async def _handle(self, incoming: Incoming) -> TurnResult:
        text = incoming.text.strip()
        if not text:
            return TurnResult(False, "", incoming.session_id, "empty")
        if len(text) > 8000:
            text = text[:8000]
        session = self.store.ensure_session(
            incoming.session_id,
            kind=incoming.kind,
            title=incoming.title or incoming.session_id,
            group_id=incoming.group_id,
        )
        settings = self.store.get_settings()
        allowed, reason = admission(settings, session, incoming.kind)
        if not allowed:
            return TurnResult(False, "", session.id, reason)

        stored = text
        if incoming.kind == "group" and incoming.sender_name:
            stored = f"{incoming.sender_name}: {text}"
        self.store.add_message(
            session.id,
            role="user",
            content=stored,
            sender_id=incoming.sender_id,
            sender_name=incoming.sender_name,
            notice=is_command(text),
        )
        notes = pin_explicit_memory(session.memory_notes, text)
        if notes != session.memory_notes:
            session = self.store.update_session(session.id, memory_notes=notes) or session

        reply, reason = wants_reply(
            settings=settings,
            session=session,
            text=text,
            addressed=incoming.addressed,
            kind=incoming.kind,
            now=utcnow(),
        )
        if not reply:
            return TurnResult(False, "", session.id, reason)

        command = parse_command(text)
        if command is not None:
            return await self._command(session, command)

        extension_reply = await self._extension(session, text, incoming)
        if extension_reply is not None:
            return await self._finish(session, extension_reply, provider=None, notice=False)

        try:
            session = await self._maintain_memory(session)
            prompt = self._prompt_messages(session)
            completion = await self.router.complete(prompt, purpose="chat")
        except (NoProviderError, AllProvidersFailed) as exc:
            notice = "我这会儿连不上模型，不过刚才的话我已经记下了。过一会儿再叫我一次就好。"
            self.store.add_message(session.id, role="assistant", content=notice, notice=True)
            self.store.add_event("error", f"会话 {session.id} 回复失败: {exc}")
            return TurnResult(True, notice, session.id, "fallback")
        return await self._finish(session, completion.text, provider=completion.provider_name, notice=False)

    async def _command(self, session: Session, command: tuple[str, str]) -> TurnResult:
        name, argument = command
        if name == "help":
            return await self._finish(session, HELP_TEXT, provider=None, notice=True)
        if name == "memory":
            fresh = self.store.get_session(session.id) or session
            parts = []
            if fresh.memory_notes.strip():
                parts.append("长期记忆：\n" + fresh.memory_notes.strip())
            if fresh.summary.strip():
                parts.append("较早的对话：\n" + fresh.summary.strip())
            text = "\n\n".join(parts) if parts else "这段对话我还没有积下摘要。刚才的话都还在原文里。"
            return await self._finish(session, text[:1500], provider=None, notice=True)
        if name == "reset":
            self.store.clear_conversation(session.id)
            text = "这段对话的上下文我已经清空了。资料和人格还在。"
            self.store.add_message(session.id, role="assistant", content=text, notice=True)
            return TurnResult(True, text, session.id, "reset")
        if name == "persona":
            return await self._switch_persona(session, argument)
        return await self._finish(session, HELP_TEXT, provider=None, notice=True)

    async def _switch_persona(self, session: Session, argument: str) -> TurnResult:
        personas = self.store.list_personas()
        if not argument:
            lines = ["可用人格："]
            for persona in personas:
                mark = "（当前默认）" if persona.is_active else ""
                lines.append(f"- {persona.name}{mark}")
            lines.append("切换时说：切换人格 名字")
            return await self._finish(session, "\n".join(lines), provider=None, notice=True)
        match = _find_persona(personas, argument)
        if match is None:
            return await self._finish(session, f"没有找到人格「{argument}」。说「人格列表」可以看全部。", provider=None, notice=True)
        self.store.update_session(session.id, persona_id=match.id)
        return await self._finish(session, f"好，这段对话之后我用「{match.name}」的方式陪你。", provider=None, notice=True)

    async def _extension(self, session: Session, text: str, incoming: Incoming) -> str | None:
        if not is_command(text) and not text.startswith("/"):
            return None
        settings = self.store.get_settings()
        disabled = set(settings.disabled_extensions)
        context = {
            "session_id": session.id,
            "kind": session.kind,
            "sender_name": incoming.sender_name,
            "sender_id": incoming.sender_id,
        }
        for extension in load_extensions():
            if extension.name in disabled:
                continue
            handler = getattr(extension.module, "on_message")
            try:
                result = handler(text, context)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception:
                logger.exception("扩展 %s 执行失败", extension.name)
                continue
            if isinstance(result, str) and result.strip():
                return result.strip()
        return None

    async def _maintain_memory(self, session: Session) -> Session:
        settings = self.store.get_settings()
        for _ in range(5):
            fresh = self.store.get_session(session.id) or session
            raw = self.store.messages_after(fresh.id, fresh.summary_until_id)
            full_tokens = estimate_messages(self._render(fresh, raw, settings))
            over_count = len(raw) > settings.keep_recent + settings.compress_after
            over_budget = full_tokens > settings.context_token_budget and len(raw) > 8
            if not over_count and not over_budget:
                break
            keep = settings.keep_recent
            if over_budget:
                keep = min(keep, max(8, len(raw) // 2))
            keep = min(keep, len(raw) - 1)
            if keep < 1:
                break
            await self._compress(fresh, raw[: len(raw) - keep])
        fresh = self.store.get_session(session.id) or session
        if settings.memory_enabled:
            pending = self.store.count_user_messages_after(fresh.id, fresh.memory_until_id)
            if pending >= settings.memory_update_every:
                await self._update_long_memory(fresh)
                fresh = self.store.get_session(session.id) or fresh
        return fresh

    async def _compress(self, session: Session, messages: list[ChatMessage]) -> None:
        messages = [item for item in messages if not item.notice]
        if not messages:
            return
        summary = session.summary
        try:
            completion = await self.router.complete(
                compression_prompt(session.summary, messages),
                temperature=0.2,
                max_tokens=800,
                purpose="compress",
            )
            summary = completion.text.strip()[:4000]
        except (NoProviderError, AllProvidersFailed, LLMError) as exc:
            summary = local_summary(session.summary, messages)
            self.store.add_event("warning", f"会话 {session.id} 改用本地摘录压缩: {exc}")
        self.store.update_session(
            session.id,
            summary=summary,
            summary_until_id=messages[-1].id,
        )

    async def _update_long_memory(self, session: Session) -> None:
        messages = self.store.messages_after(session.id, session.memory_until_id)
        if not messages:
            return
        try:
            completion = await self.router.complete(
                memory_prompt(session.memory_notes, messages),
                temperature=0.2,
                max_tokens=800,
                purpose="memory",
            )
            notes = completion.text.strip()[:3000] or session.memory_notes
        except (NoProviderError, AllProvidersFailed, LLMError) as exc:
            self.store.add_event("warning", f"会话 {session.id} 长期记忆更新失败: {exc}")
            return
        for line in session.memory_notes.splitlines():
            item = line.strip()
            if item.startswith("- ") and "记住" in item and item not in notes:
                notes = (notes + "\n" + item).strip()
        self.store.update_session(session.id, memory_notes=notes[:3000], memory_until_id=messages[-1].id)

    def _prompt_messages(self, session: Session, raw: list[ChatMessage] | None = None) -> list[dict]:
        settings = self.store.get_settings()
        recent = raw if raw is not None else self.store.messages_after(session.id, session.summary_until_id)
        return self._render(session, recent, settings)

    def _render(self, session: Session, recent: list[ChatMessage], settings) -> list[dict]:
        persona = self._persona_for(session)
        knowledge = "\n\n".join(part for part in (settings.knowledge, session.knowledge) if part and part.strip())
        system = render_system(
            bot_name=settings.bot_name,
            persona=persona,
            session=session,
            knowledge=knowledge,
        )
        return build_messages(system, recent)

    def _persona_for(self, session: Session) -> Persona | None:
        if session.persona_id:
            persona = self.store.get_persona(session.persona_id)
            if persona is not None:
                return persona
        return self.store.active_persona()

    async def _finish(self, session: Session, text: str, *, provider: str | None, notice: bool) -> TurnResult:
        cleaned = text.strip()
        if len(cleaned) > 4000:
            cleaned = cleaned[:4000] + "…"
        self.store.add_message(session.id, role="assistant", content=cleaned, notice=notice)
        if not notice:
            self.store.update_session(session.id, last_reply_at=iso())
        return TurnResult(True, cleaned, session.id, "ok", provider=provider)


def _find_persona(personas: list[Persona], name: str) -> Persona | None:
    wanted = name.strip().lower()
    for persona in personas:
        if persona.name.lower() == wanted:
            return persona
    for persona in personas:
        if wanted and wanted in persona.name.lower():
            return persona
    return None
