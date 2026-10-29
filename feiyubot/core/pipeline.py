"""把一条群消息或网页消息变成回复，并维护持久上下文。"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import time
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
from feiyubot.ling import config as ling_config
from feiyubot.ling.commands import HELP as LING_HELP
from feiyubot.ling.commands import parse as parse_ling
from feiyubot.ling.express import Decider, in_active_hours, split_bubbles
from feiyubot.ling.memory_level import affinity_stage, bigram_score, judge_level
from feiyubot.ling.night import in_fatigue, rolled_awake, stage_at
from feiyubot.ling.recall import decay_if_due, remember, should_inject
from feiyubot.ling.tools import allow_call, current_time_text, maybe_tool, mc_status, peek_url, weather_text

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
    humanize: bool = False
    message_id: str = ""
    is_admin: bool = False


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
        self.decider = Decider()
        self._tool_hits: dict[str, list[float]] = {}
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

        ling_args = parse_ling(text)
        if ling_args is not None:
            answer = await self._ling_command(incoming, session, ling_args)
            return await self._finish(session, answer, provider=None, notice=True, humanize=False)

        cfg = ling_config.load(self.store) if incoming.humanize else None
        if cfg and cfg["enabled"]:
            self.decider.observe(session.id, text)
            self._remember_atom(incoming, session, text, cfg)
            asleep = self._night_turn(incoming, session, text, cfg)
            await self._maybe_dream()
            if asleep is not None:
                if asleep.replied:
                    return await self._finish(session, asleep.text, provider=None, notice=False, humanize=False)
                return asleep
            if incoming.kind == "group" and not is_command(text):
                decision = self.decider.decide(
                    session_id=session.id,
                    kind=incoming.kind,
                    text=text,
                    addressed=incoming.addressed,
                    persona_name=cfg["persona_name"] or settings.bot_name,
                    threshold=float(cfg["reply_threshold"]),
                    window=float(cfg["reply_window_seconds"]),
                    active=in_active_hours(str(cfg["active_hours"])),
                )
                if cfg["decision_log"]:
                    self.store.add_event("info", f"{session.id} {decision.reason}")
                if not decision.should_reply:
                    return TurnResult(False, "", session.id, decision.reason)
            else:
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
        else:
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
            extra = await self._ling_context(incoming, session, text)
            prompt = self._prompt_messages(session, extra=extra)
            completion = await self.router.complete(prompt, purpose="chat")
        except (NoProviderError, AllProvidersFailed) as exc:
            notice = "我这会儿连不上模型，不过刚才的话我已经记下了。过一会儿再叫我一次就好。"
            self.store.add_message(session.id, role="assistant", content=notice, notice=True)
            self.store.add_event("error", f"会话 {session.id} 回复失败: {exc}")
            return TurnResult(True, notice, session.id, "fallback")
        result = await self._finish(
            session,
            completion.text,
            provider=completion.provider_name,
            notice=False,
            humanize=bool(cfg and cfg["enabled"]),
            kind=incoming.kind,
            max_group=int(cfg["max_bubbles_group"]) if cfg else 2,
            max_private=int(cfg["max_bubbles_private"]) if cfg else 3,
        )
        if cfg and cfg["enabled"]:
            self.decider.mark_replied(session.id)
            subject = incoming.sender_id or session.id
            self.store.add_affinity(subject, 1)
        return result

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

    def _prompt_messages(self, session: Session, raw: list[ChatMessage] | None = None, extra: str = "") -> list[dict]:
        settings = self.store.get_settings()
        recent = raw if raw is not None else self.store.messages_after(session.id, session.summary_until_id)
        return self._render(session, recent, settings, extra=extra)

    def _render(self, session: Session, recent: list[ChatMessage], settings, extra: str = "") -> list[dict]:
        persona = self._persona_for(session)
        knowledge = "\n\n".join(part for part in (settings.knowledge, session.knowledge, extra) if part and part.strip())
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

    async def _finish(
        self,
        session: Session,
        text: str,
        *,
        provider: str | None,
        notice: bool,
        humanize: bool = False,
        kind: str = "web",
        max_group: int = 2,
        max_private: int = 3,
    ) -> TurnResult:
        cleaned = text.strip()
        bubbles: list[str] = []
        if humanize and not notice:
            bubbles = split_bubbles(cleaned, kind=kind, max_group=max_group, max_private=max_private)
            cleaned = "\n".join(bubbles)
        if len(cleaned) > 4000:
            cleaned = cleaned[:4000] + "…"
        self.store.add_message(session.id, role="assistant", content=cleaned, notice=notice)
        if not notice:
            self.store.update_session(session.id, last_reply_at=iso())
        return TurnResult(True, cleaned, session.id, "ok", provider=provider, bubbles=bubbles)

    def _remember_atom(self, incoming: Incoming, session: Session, text: str, cfg: dict) -> None:
        if "记住" not in text and not any(word in text for word in ("我叫", "约定", "不许", "我最喜欢")):
            return
        subject = incoming.sender_id or session.id
        stage = affinity_stage(self.store.affinity_of(subject))
        level, tags = judge_level(text, stage=stage)
        remember(
            self.store,
            scope="group" if incoming.kind == "group" else "user",
            subject=subject,
            content=text,
            level=level,
            tags=tags,
        )

    def _night_state(self) -> dict:
        import json

        raw = self.store.get_meta("ling_night")
        if not raw:
            return {"asleep": False, "sleep_at": 0, "kind": "night", "since": 0, "energy": 100}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        data.setdefault("asleep", False)
        data.setdefault("sleep_at", 0)
        data.setdefault("kind", "night")
        data.setdefault("since", 0)
        data.setdefault("energy", 100)
        return data

    def _save_night(self, state: dict) -> None:
        import json

        self.store.set_meta("ling_night", json.dumps(state, ensure_ascii=False))

    def _tick_energy(self, state: dict) -> str | None:
        now = time.time()
        last = float(state.get("last_energy_at") or now)
        minutes = max(0.0, (now - last) / 60)
        fatigue = in_fatigue()
        energy = float(state.get("energy") or 100)
        if fatigue:
            energy -= minutes / 3.0
            energy -= 2
            state["fatigue_turns"] = int(state.get("fatigue_turns") or 0) + 1
        else:
            energy += minutes / 10.0
            energy += 1
            state["fatigue_turns"] = 0
        state["energy"] = max(0.0, min(100.0, energy))
        state["last_energy_at"] = now
        return fatigue

    def _past_latest_sleep(self, fatigue: str | None, spec: str) -> bool:
        if fatigue != "night" or not spec.strip():
            return False
        try:
            hour, minute = [int(part) for part in spec.strip().split(":", 1)]
        except ValueError:
            return False
        from datetime import datetime
        from zoneinfo import ZoneInfo

        clock = datetime.now(ZoneInfo("Asia/Shanghai"))
        current = clock.hour * 60 + clock.minute
        start = hour * 60 + minute
        return start <= current < 7 * 60

    def _night_turn(self, incoming: Incoming, session: Session, text: str, cfg: dict):
        state = self._night_state()
        if not cfg.get("allow_sleep"):
            if state.get("asleep"):
                state["asleep"] = False
                state["unread"] = []
            self._tick_energy(state)
            self._save_night(state)
            return None
        if state["asleep"]:
            state["since"] = int(state.get("since") or 0) + 1
            unread = [str(item) for item in state.get("unread") or [] if str(item).strip()]
            if text.strip():
                unread.append(text.strip()[:80])
            state["unread"] = unread[-20:]
            stage = stage_at(int(state.get("sleep_at") or 0), time.time(), kind=str(state.get("kind") or "night"))
            factor = float((stage or {}).get("wake_factor") or 1.0)
            mode = cfg.get("wake_mode") or "private_only"
            can_wake = mode == "both" or (mode == "private_only" and incoming.kind != "group")
            if mode != "never" and can_wake and rolled_awake(state["since"], factor=factor):
                previous = state["unread"][:-1]
                state["asleep"] = False
                state["since"] = 0
                state["energy"] = 70
                state["unread"] = []
                self._save_night(state)
                if previous:
                    self.store.set_meta("ling_crawl", "睡着时没读完的：\n" + "\n".join(previous)[:800])
                return None
            self._save_night(state)
            return TurnResult(False, "", session.id, "asleep")
        fatigue = self._tick_energy(state)
        min_turns = int(cfg.get("min_turns_before_sleep") or 4)
        tired = bool(fatigue) and float(state["energy"]) <= 0 and int(state.get("fatigue_turns") or 0) >= min_turns
        if tired or self._past_latest_sleep(fatigue, str(cfg.get("latest_sleep") or "")):
            state.update({"asleep": True, "sleep_at": int(time.time()), "kind": fatigue or "night", "since": 0, "unread": []})
            self._save_night(state)
            return TurnResult(True, "我先睡了，醒了再看你们说的", session.id, "goodnight")
        self._save_night(state)
        return None

    async def _maybe_dream(self) -> None:
        state = self._night_state()
        if not state.get("asleep"):
            return
        stage = stage_at(int(state.get("sleep_at") or 0), time.time(), kind=str(state.get("kind") or "night"))
        if not stage or stage.get("key") != "rem":
            return
        cycle = int(stage.get("cycle") or 0)
        if int(state.get("dream_cycle") or 0) == cycle:
            return
        state["dream_cycle"] = cycle
        self._save_night(state)
        atoms = self.store.list_ling_atoms(limit=3)
        material = "；".join(str(item["content"])[:80] for item in atoms)
        if not material:
            return
        try:
            completion = await self.router.complete(
                [
                    {"role": "system", "content": "把素材写成一句第一人称的梦话。素材里没有的不要编，不要解释。"},
                    {"role": "user", "content": material},
                ],
                purpose="dream",
            )
            body = completion.text.strip()
        except Exception:
            return
        if not body:
            return
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        moment = datetime.now(ZoneInfo("Asia/Shanghai"))
        if moment.hour < 5:
            moment -= timedelta(days=1)
        level = max(int(item["level"]) for item in atoms)
        self.store.add_dream(moment.strftime("%Y-%m-%d"), body[:400], level)

    async def _ling_context(self, incoming: Incoming, session: Session, text: str) -> str:
        if not incoming.humanize:
            return ""
        cfg = ling_config.load(self.store)
        if not cfg["enabled"]:
            return ""
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        decay_if_due(self.store, str(cfg["forgetting_mode"]), today)
        parts = ["现在是 " + current_time_text() + "。"]
        if cfg.get("style_hint", True):
            parts.insert(0, "说话短一点，像朋友。不要用 emoji，句末不要加句号。")
        crawl = (self.store.get_meta("ling_crawl") or "").strip()
        if crawl:
            parts.append(crawl)
            self.store.set_meta("ling_crawl", "")
        subject = incoming.sender_id or session.id
        stage = affinity_stage(self.store.affinity_of(subject))
        if stage >= 2:
            own = self.store.list_ling_atoms(subject=subject, limit=3)
            if own:
                parts.append("我对这个人的认识：" + "；".join(str(item["content"])[:40] for item in own))
        scored: list[tuple[float, dict]] = []
        for atom in self.store.list_ling_atoms(limit=80):
            score = bigram_score(text, str(atom["content"]))
            if score <= 0 and subject == atom["subject"]:
                continue
            if score > 0 or atom["subject"] == subject:
                scored.append((score + atom["level"] / 10, atom))
        scored.sort(key=lambda item: item[0], reverse=True)
        now = datetime.now(timezone.utc)
        chosen = []
        for score, atom in scored:
            if len(chosen) >= int(cfg["inject_top_k"]):
                break
            if score <= 0 or not should_inject(atom, text, now):
                continue
            chosen.append(f"- {atom['content']}")
            self.store.touch_ling_atom(int(atom["id"]))
            self.store.mark_ling_injected(int(atom["id"]))
        if chosen:
            parts.append("想起的事（和当前对话冲突时，以当前对话为准）：\n" + "\n".join(chosen))
        tool = maybe_tool(text)
        if tool:
            allowed, stamps = allow_call(self._tool_hits.get(session.id, []), time.time())
            self._tool_hits[session.id] = stamps
            name, arg = tool
            if not allowed:
                parts.append("查询结果：这会儿查得太勤，等一分钟再问。")
            elif name == "status":
                night = self._night_state()
                parts.append(f"查询结果：记忆 {self.store.count_ling_atoms()} 条，精力 {int(night.get('energy') or 0)}")
            elif name == "time":
                parts.append("查询结果：" + current_time_text())
            elif name == "weather":
                parts.append("查询结果：" + await weather_text(arg or str(cfg["weather_city"])))
            elif name == "web":
                parts.append("查询结果：" + await peek_url(arg))
            elif name == "mc":
                parts.append("查询结果：" + await mc_status(arg))
            elif name == "translate" and arg:
                parts.append(f"请把下面这句话翻译成自然的中文或英文，只给译文：{arg}")
        return "\n\n".join(parts)

    async def _ling_command(self, incoming: Incoming, session: Session, args: list[str]) -> str:
        if not args:
            return LING_HELP
        action, rest = args[0], args[1:]
        cfg = ling_config.load(self.store)
        if action in {"状态", "status"}:
            night = self._night_state()
            stage = ""
            if night.get("asleep"):
                found = stage_at(int(night.get("sleep_at") or 0), time.time(), kind=str(night.get("kind") or "night"))
                stage = f"，正在{found['label']}" if found else "，在睡"
            return (
                f"{cfg['persona_name']} · 记忆 {self.store.count_ling_atoms()} 条"
                f" · 精力 {int(night.get('energy') or 0)}{stage}"
            )
        if action in {"记忆", "memory"}:
            keyword = " ".join(rest).strip()
            if not keyword:
                return "要找什么"
            hits = [
                str(atom["content"])
                for atom in self.store.list_ling_atoms(limit=80)
                if keyword in str(atom["content"])
            ][:5]
            return "\n".join(hits) if hits else "没想起来相关的事"
        if action in {"记住", "remember"}:
            content = " ".join(rest).strip()
            if not content:
                return "要记什么"
            if not incoming.is_admin:
                return "这个要管理员才能写"
            level, tags = judge_level(content, base=5)
            atom_id = self.store.add_ling_atom(
                scope="group" if incoming.kind == "group" else "user",
                subject=incoming.sender_id or session.id,
                content=content,
                level=level,
                tags=tags,
                strength=STRENGTH.get(level, 0.95),
            )
            return f"记住了（#{atom_id}）"
        if action in {"忘掉", "forget"}:
            keyword = " ".join(rest).strip()
            if not keyword:
                return "要忘掉什么"
            if not incoming.is_admin:
                return "这个要管理员才能删"
            count = self.store.forget_ling_atoms(keyword)
            return f"忘掉了 {count} 条" if count else "没找到相关的记忆"
        if action in {"空间", "qzone"}:
            from feiyubot.ling.qzone import feed_text, publish_text

            sub = rest[0] if rest else "看"
            if sub in {"发", "post", "publish"}:
                if not incoming.is_admin:
                    return "这个要管理员才能发"
                if not cfg["qzone_allow_write"]:
                    return "空间写操作还关着"
                return await publish_text(str(cfg["qzone_cookie"]), str(cfg["qzone_uin"]), " ".join(rest[1:]))
            return await feed_text(str(cfg["qzone_cookie"]), str(cfg["qzone_uin"]))
        if action in {"日记", "diary"}:
            rows = self.store.list_diary(limit=1)
            return rows[0]["body"] if rows else "还没写过日记"
        if action in {"兼容", "compat"}:
            return "拟人、记忆、节奏和输出守卫都由飞鱼自己负责。这里没有别的插件要让位。"
        if action in {"签名", "nick"}:
            if not incoming.is_admin:
                return "这个要管理员才能改"
            from feiyubot.ling.qqact import set_signature

            return await set_signature(" ".join(rest))
        if action in {"名片", "card"}:
            if not incoming.is_admin:
                return "这个要管理员才能改"
            from feiyubot.ling.qqact import set_group_card

            return await set_group_card(str(incoming.group_id or ""), " ".join(rest))
        if action in {"调试", "debug"}:
            if not incoming.is_admin:
                return "这个要管理员"
            if not rest:
                return f"决策日志现在是{'开' if cfg['decision_log'] else '关'}的"
            enabled = rest[0] in {"开", "on", "1", "true"}
            ling_config.save(self.store, {"decision_log": enabled})
            return f"决策日志已{'打开' if enabled else '关闭'}"
        return LING_HELP


def _find_persona(personas: list[Persona], name: str) -> Persona | None:
    wanted = name.strip().lower()
    for persona in personas:
        if persona.name.lower() == wanted:
            return persona
    for persona in personas:
        if wanted and wanted in persona.name.lower():
            return persona
    return None
