"""主动找人。默认关。启动后三分钟内什么都不做，睡着、额度用完或刚发过都不发。"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from feiyubot.ling import config as ling_config
from feiyubot.service import Service


def _line(hour: int) -> str:
    if 6 <= hour < 11:
        return "早，醒了吗"
    if 11 <= hour < 18:
        return "刚想到你，在吗"
    return "还没睡的话回我一句"


async def tick(service: Service) -> None:
    cfg = ling_config.load(service.store)
    if not cfg["proactive_enabled"] or int(cfg["proactive_daily_cap"]) <= 0:
        return
    night_raw = service.store.get_meta("ling_night") or ""
    if '"asleep":true' in night_raw.replace(" ", ""):
        return
    now = time.time()
    sent = service.store.get_meta("ling_proactive_at")
    if sent and now - float(sent) < 6 * 3600:
        return
    moment = datetime.now(ZoneInfo("Asia/Shanghai"))
    day_key = moment.strftime("%Y-%m-%d")
    used_raw = service.store.get_meta("ling_proactive_day") or ""
    used = 0
    if used_raw.startswith(day_key + ":"):
        try:
            used = int(used_raw.split(":", 1)[1])
        except ValueError:
            used = 0
    if used >= int(cfg["proactive_daily_cap"]):
        return
    try:
        import nonebot
    except Exception:
        return
    bots = list(nonebot.get_bots().values())
    if not bots:
        return
    sessions = service.store.list_sessions("group")
    if not sessions:
        return
    target = sessions[0]
    session_id = str(target["id"])
    recent = service.store.list_messages(session_id, limit=3)
    if len(recent) < 3:
        return
    line = _line(moment.hour)
    if recent[-1].role == "assistant" and recent[-1].content == line:
        return
    group_id = target.get("group_id") or session_id.removeprefix("group:")
    await bots[0].call_api("send_group_msg", group_id=int(group_id), message=line)
    service.store.set_meta("ling_proactive_at", str(now))
    service.store.set_meta("ling_proactive_day", f"{day_key}:{used + 1}")
    service.store.add_message(session_id, role="assistant", content=line, notice=False)
    subject = recent[-1].sender_id or session_id
    service.store.add_affinity(str(subject or session_id), 2)
