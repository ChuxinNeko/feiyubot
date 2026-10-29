"""OneBot v11 群消息：记入群上下文，并在被唤醒时回复。"""

import asyncio
import os
import time

from nonebot import on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment, PokeNotifyEvent
from nonebot.log import logger

from feiyubot.core.pipeline import Incoming
from feiyubot.ling import config as ling_config
from feiyubot.ling.express import bubble_delays, quote_this
from feiyubot.ling.perceive import perceive, render_forward, render_quote
from feiyubot.service import get_service

group_chat = on_message(priority=10, block=False)
poke_back = on_notice(priority=10, block=False)
_LAST_POKE: dict[str, float] = {}
_LAST_QUOTE: dict[str, float] = {}


@group_chat.handle()
async def _(bot: Bot, event: GroupMessageEvent) -> None:
    if event.user_id == event.self_id:
        return
    text = await _enrich(bot, event)
    if not text:
        return
    try:
        service = get_service()
    except RuntimeError:
        logger.warning("飞鱼尚未就绪，忽略这条群消息")
        return
    sender = event.sender
    sender_name = (sender.card or sender.nickname or "").strip() or str(event.user_id)
    cfg = ling_config.load(service.store)
    admin = str(event.user_id) in {str(item) for item in cfg["extra_admins"]}
    if cfg["include_group_role"] and str(getattr(sender, "role", "") or "") in {"owner", "admin"}:
        admin = True
    result = await service.pipeline.handle(
        Incoming(
            session_id=f"group:{event.group_id}",
            kind="group",
            text=text,
            sender_id=str(event.user_id),
            sender_name=sender_name,
            title=await _group_title(bot, event, service),
            group_id=str(event.group_id),
            addressed=_addressed(event),
            humanize=bool(cfg["enabled"]),
            message_id=str(event.message_id),
            is_admin=admin,
        )
    )
    if not result.replied or not result.text:
        logger.debug(f"群 {event.group_id} 不回复: {result.reason}")
        return
    bubbles = result.bubbles or [result.text]
    quote = quote_this(
        message_id=str(event.message_id),
        text=text,
        kind="group",
        last_quote_at=_LAST_QUOTE.get(str(event.group_id), 0.0),
        was_quoted=any(segment.type == "reply" for segment in event.message),
    )
    if quote:
        _LAST_QUOTE[str(event.group_id)] = time.time()
    delays = bubble_delays(bubbles, len(text))
    skip_delay = os.environ.get("FEIYU_LING_NO_DELAY") == "1"
    try:
        for index, bubble in enumerate(bubbles):
            if not skip_delay:
                await asyncio.sleep(delays[index] if index < len(delays) else 0.6)
            message = MessageSegment.reply(event.message_id) + bubble if quote and index == 0 else bubble
            await bot.send(event, message)
    except Exception:
        logger.exception(f"群 {event.group_id} 发送失败")


@poke_back.handle()
async def _(bot: Bot, event: PokeNotifyEvent) -> None:
    if not event.group_id or event.target_id != event.self_id or event.user_id == event.self_id:
        return
    key = f"{event.group_id}:{event.user_id}"
    now = time.time()
    if now - _LAST_POKE.get(key, 0.0) < 60:
        return
    _LAST_POKE[key] = now
    try:
        await bot.call_api("group_poke", group_id=event.group_id, user_id=event.user_id)
    except Exception:
        logger.debug(f"回戳 {event.user_id} 失败")


async def _enrich(bot: Bot, event: GroupMessageEvent) -> str:
    plain = perceive(event.message) or event.get_plaintext().strip()

    async def _expand() -> str:
        extra: list[str] = []
        for segment in event.message:
            if segment.type == "forward":
                forward_id = segment.data.get("id") or event.message_id
                try:
                    data = await bot.call_api("get_forward_msg", message_id=forward_id)
                except Exception:
                    continue
                nodes = []
                if isinstance(data, dict):
                    nodes = data.get("messages") or data.get("message") or []
                rendered = render_forward(nodes)
                if rendered:
                    extra.append(rendered)
            elif segment.type == "reply":
                reply_id = segment.data.get("id")
                if not reply_id:
                    continue
                try:
                    data = await bot.call_api("get_msg", message_id=int(reply_id))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
                name = str((sender or {}).get("nickname") or data.get("user_id") or "")
                raw = data.get("message")
                if isinstance(raw, list):
                    body = perceive(raw) if raw and not isinstance(raw[0], dict) else ""
                    if not body:
                        from feiyubot.ling.perceive import _plain_segments

                        body = _plain_segments(raw)
                else:
                    body = str(data.get("raw_message") or raw or "")
                rendered = render_quote(name, body)
                if rendered:
                    extra.append(rendered)
        if not extra:
            return plain
        return (plain + "\n" + "\n".join(extra)).strip()

    try:
        return await asyncio.wait_for(_expand(), timeout=6)
    except Exception:
        return plain


def _addressed(event: GroupMessageEvent) -> bool:
    if event.to_me:
        return True
    self_id = str(event.self_id)
    for segment in event.message:
        if segment.type == "at" and str(segment.data.get("qq", "")) == self_id:
            return True
    return False


async def _group_title(bot: Bot, event: GroupMessageEvent, service) -> str:
    session_id = f"group:{event.group_id}"
    current = service.store.get_session(session_id)
    if current and not current.title.startswith("群 ") and current.title != session_id:
        return current.title
    try:
        info = await bot.call_api("get_group_info", group_id=event.group_id)
    except Exception:
        logger.debug(f"读取群 {event.group_id} 名称失败")
        return f"群 {event.group_id}"
    name = ""
    if isinstance(info, dict):
        name = str(info.get("group_name") or "").strip()
    return name or f"群 {event.group_id}"
