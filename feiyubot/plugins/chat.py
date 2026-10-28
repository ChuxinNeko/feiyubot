"""OneBot v11 群消息：记入群上下文，并在被唤醒时回复。"""

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.log import logger

from feiyubot.core.pipeline import Incoming
from feiyubot.service import get_service

group_chat = on_message(priority=10, block=False)


@group_chat.handle()
async def _(bot: Bot, event: GroupMessageEvent) -> None:
    if event.user_id == event.self_id:
        return
    text = event.get_plaintext().strip()
    if not text:
        return
    try:
        service = get_service()
    except RuntimeError:
        logger.warning("飞鱼尚未就绪，忽略这条群消息")
        return
    sender = event.sender
    sender_name = (sender.card or sender.nickname or "").strip() or str(event.user_id)
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
        )
    )
    if not result.replied or not result.text:
        logger.debug(f"群 {event.group_id} 不回复: {result.reason}")
        return
    try:
        await bot.send(event, result.text[:4000])
    except Exception:
        logger.exception(f"群 {event.group_id} 发送失败")


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
