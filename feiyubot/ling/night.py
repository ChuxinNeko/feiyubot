"""长夜如梦：精力、入睡、睡眠阶段和叫醒。阶段按入睡时间现算，不靠心跳推进。"""

from __future__ import annotations

import random
import time

STAGE_CN = {"n1": "刚入睡", "n2": "浅层睡眠", "n3": "深度睡眠", "rem": "快速眼动"}
WAKE_FACTOR = {"n1": 1.3, "n2": 0.8, "n3": 0.45, "rem": 1.1}


def _cycle(index: int) -> list[tuple[str, float]]:
    deep = max(0, round(36 * (1 - 0.28 * index)))
    rem = min(28, 10 + 6 * index)
    rest = 90 - (8 if index == 0 else 0) - deep - rem
    if rest < 6:
        over = 6 - rest
        take = min(over, rem)
        rem -= take
        over -= take
        deep -= min(over, deep)
        rest = max(2, 90 - (8 if index == 0 else 0) - deep - rem)
    before = round(rest * 0.6)
    after = rest - before
    parts: list[tuple[str, float]] = []
    if index == 0:
        parts.append(("n1", 8))
    parts.append(("n2", before))
    if deep:
        parts.append(("n3", deep))
    if after:
        parts.append(("n2", after))
    if rem:
        parts.append(("rem", rem))
    return parts


def stage_at(sleep_at: int, now: float, *, kind: str = "night") -> dict | None:
    if sleep_at <= 0 or now < sleep_at:
        return None
    if kind == "noon":
        elapsed = (now - sleep_at) / 60
        if elapsed < 4:
            key = "n1"
        elif elapsed < 25:
            key = "n2"
        else:
            key = "rem"
        return {"key": key, "label": STAGE_CN[key], "cycle": 1, "wake_factor": WAKE_FACTOR[key]}
    cursor = float(sleep_at)
    cycle = 0
    while cycle < 24:
        for key, minutes in _cycle(cycle):
            end = cursor + minutes * 60
            if now < end:
                return {
                    "key": key,
                    "label": STAGE_CN[key],
                    "cycle": cycle + 1,
                    "minutes_left": max(0, int((end - now) / 60)),
                    "wake_factor": WAKE_FACTOR[key],
                }
            cursor = end
        cycle += 1
    return {"key": "n2", "label": STAGE_CN["n2"], "cycle": 24, "minutes_left": 0, "wake_factor": 0.8}


def in_fatigue(now: time.struct_time | None = None, zone: str = "Asia/Shanghai") -> str | None:
    if now is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        clock = datetime.now(ZoneInfo(zone)).timetuple()
    else:
        clock = now
    minutes = clock.tm_hour * 60 + clock.tm_min
    if 23 * 60 + 30 <= minutes or minutes < 7 * 60:
        return "night"
    if 13 * 60 <= minutes < 14 * 60 + 30:
        return "noon"
    return None


def wake_chance(messages_since_sleep: int, *, start: int = 2, span: int = 4, factor: float = 1.0) -> float:
    """睡着后第 start 条起有机会，之后 span 条把概率平分完。"""
    if messages_since_sleep < start:
        return 0.0
    index = messages_since_sleep - start
    if index >= span:
        return min(1.0, factor)
    return min(1.0, ((index + 1) / span) * factor)


def rolled_awake(messages_since_sleep: int, *, factor: float = 1.0, rng: random.Random | None = None) -> bool:
    chance = wake_chance(messages_since_sleep, factor=factor)
    roll = (rng or random).random()
    return roll < chance
