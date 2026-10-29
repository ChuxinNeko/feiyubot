"""改签名、改群名片。协议端不支持时说人话。"""

from __future__ import annotations


def _bots() -> list:
    try:
        import nonebot
    except Exception:
        return []
    return list(nonebot.get_bots().values())


async def set_signature(text: str) -> str:
    text = text.strip()
    if not text:
        return "签名写什么"
    bots = _bots()
    if not bots:
        return "现在没有连上 QQ"
    bot = bots[0]
    try:
        await bot.call_api("set_self_longnick", longNick=text[:60])
        return "签名改好了"
    except Exception:
        pass
    try:
        await bot.call_api("set_qq_profile", nickname="", personal_note=text[:60])
        return "签名改好了"
    except Exception:
        return "这个协议端改不了签名"


async def set_group_card(group_id: str, card: str) -> str:
    card = card.strip()
    if not group_id or not card:
        return "要在群里说，并且带上新名片"
    bots = _bots()
    if not bots:
        return "现在没有连上 QQ"
    bot = bots[0]
    user_id = getattr(bot, "self_id", None)
    try:
        await bot.call_api("set_group_card", group_id=int(group_id), user_id=int(user_id), card=card[:60])
        return "名片改好了"
    except Exception:
        return "这个协议端改不了名片"
