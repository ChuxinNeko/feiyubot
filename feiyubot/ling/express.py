"""回不回、分句、输出守卫、引用概率和发送节奏。"""

from __future__ import annotations

import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

QUESTION_HINTS = ("?", "？", "吗", "呢", "怎么", "为什么", "为啥", "能不能", "是不是", "有没有", "多少")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?…～~])")
_CLAUSE_RE = re.compile(r"(?<=[，,、])")
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U0001f000-\U0001f2ff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\U0000fe0f"
    "\U0000200d"
    "\U00002b00-\U00002bff"
    "\U0000fe00-\U0000fe0f"
    "]+",
    flags=re.UNICODE,
)
_KAOMOJI_RE = re.compile(r"[（(][^（）()]{0,12}[ω・∀▽｀´°￣][^（）()]{0,12}[)）]")
FORBID = ("作为AI", "作为一个AI", "希望对你有帮助", "总结一下", "有什么可以帮你")


@dataclass
class Decision:
    should_reply: bool
    score: float
    threshold: float
    reason: str
    signals: dict[str, float] = field(default_factory=dict)


class Decider:
    def __init__(self) -> None:
        self._last_reply: dict[str, float] = {}
        self._recent: dict[str, list[tuple[float, str]]] = defaultdict(list)

    def observe(self, session_id: str, text: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        bucket = self._recent[session_id]
        bucket.append((now, text))
        cutoff = now - 60
        while bucket and bucket[0][0] < cutoff:
            bucket.pop(0)

    def mark_replied(self, session_id: str, now: float | None = None) -> None:
        self._last_reply[session_id] = time.time() if now is None else now

    def decide(
        self,
        *,
        session_id: str,
        kind: str,
        text: str,
        addressed: bool,
        persona_name: str,
        threshold: float = 35,
        window: float = 300,
        active: bool = True,
        now: float | None = None,
    ) -> Decision:
        now = time.time() if now is None else now
        signals: dict[str, float] = {}
        is_group = kind == "group"
        if not is_group:
            signals["私聊"] = 100.0
        else:
            if addressed:
                signals["被点名"] = 100.0
            elif persona_name and persona_name in (text or ""):
                signals["叫了名字"] = 60.0
            elif "绫" in (text or "") or "飞鱼" in (text or ""):
                signals["叫了名字"] = 60.0
            if any(hint in (text or "") for hint in QUESTION_HINTS):
                signals["问句"] = 25.0
            overlap = self._overlap(session_id, text)
            if overlap:
                signals["话题相关"] = overlap
            density = len(self._recent.get(session_id, []))
            if density > 8:
                signals["群太吵"] = -min(30.0, (density - 8) * 5.0)
        last = self._last_reply.get(session_id, 0.0)
        if is_group and last and now - last < 20 and not addressed:
            signals["刚回过"] = -40.0
        if is_group and not active and not addressed:
            signals["静默时段"] = -999.0
        limit = float(threshold)
        if last and now - last < window:
            limit = max(5.0, limit - 15.0)
        score = sum(signals.values())
        should = score >= limit
        if not should and score > 0 and random.random() < min(1.0, score / max(limit, 1.0)):
            should = True
        reason = "、".join(f"{key}{value:+.0f}" for key, value in signals.items()) or "无信号"
        return Decision(should, round(score, 1), limit, f"{reason} → {score:.0f}/{limit:.0f}", signals)

    def _overlap(self, session_id: str, text: str) -> float:
        recent = [item for _, item in self._recent.get(session_id, [])[-6:-1]]
        if not recent or not text:
            return 0.0
        target = set(text)
        best = 0.0
        for item in recent:
            other = set(item)
            if not other:
                continue
            best = max(best, len(target & other) / max(1, len(target | other)))
        if best >= 0.72:
            return 20.0
        if best >= 0.5:
            return 10.0
        return 0.0


def in_active_hours(spec: str, now: time.struct_time | None = None) -> bool:
    try:
        start_text, end_text = spec.split("-", 1)
        start_h, start_m = [int(part) for part in start_text.strip().split(":")]
        end_h, end_m = [int(part) for part in end_text.strip().split(":")]
    except (ValueError, AttributeError):
        return True
    if now is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        clock = datetime.now(ZoneInfo("Asia/Shanghai")).timetuple()
    else:
        clock = now
    current = clock.tm_hour * 60 + clock.tm_min
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def clean_text(text: str, *, forbid: list[str] | None = None) -> str:
    result = text or ""
    result = _EMOJI_RE.sub("", result)
    result = _KAOMOJI_RE.sub("", result)
    for phrase in forbid if forbid is not None else FORBID:
        if phrase:
            result = result.replace(phrase, "")
    result = result.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    result = re.sub(r"[ \t\u3000]{2,}", " ", result).strip()
    while result and result[-1] in "。｡":
        result = result[:-1].rstrip()
    return result


def split_bubbles(text: str, *, kind: str = "group", max_group: int = 2, max_private: int = 3) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= 14:
        cleaned = clean_text(text)
        return [cleaned] if cleaned else []
    parts = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(part) < 6:
            merged[-1] += part
        else:
            merged.append(part)
    pieces: list[str] = []
    for part in merged:
        if len(part) <= 32:
            pieces.append(part)
            continue
        clauses = [item for item in _CLAUSE_RE.split(part) if item.strip()]
        if len(clauses) <= 1:
            pieces.append(part)
            continue
        buffer = ""
        for clause in clauses:
            if buffer and len(buffer) + len(clause) > 32:
                pieces.append(buffer.strip())
                buffer = clause
            else:
                buffer += clause
        if buffer.strip():
            pieces.append(buffer.strip())
    if len(pieces) > 1 and random.random() < 0.2:
        index = random.randrange(len(pieces) - 1)
        pieces = pieces[:index] + [pieces[index] + pieces[index + 1]] + pieces[index + 2 :]
    limit = max_private if kind != "group" else max_group
    if len(pieces) > limit:
        pieces = pieces[: limit - 1] + [" ".join(pieces[limit - 1 :])]
    cleaned = [item for item in (clean_text(part) for part in pieces) if item]
    return cleaned or ([clean_text(text)] if clean_text(text) else [])


def quote_this(
    *,
    message_id: str,
    text: str,
    kind: str,
    last_quote_at: float,
    now: float | None = None,
    base: float = 0.08,
    ceiling: float = 0.35,
    cooldown: float = 30,
    was_quoted: bool = False,
) -> bool:
    now = time.time() if now is None else now
    if not message_id or message_id in {"0", "None", "null"}:
        return False
    if cooldown > 0 and now - last_quote_at < cooldown:
        return False
    probability = base
    if was_quoted:
        probability += 0.15
    if len(text) > 80:
        probability += 0.10
    if kind != "group":
        probability -= 0.03
    probability = min(ceiling, max(0.0, probability))
    return random.random() < probability


def bubble_delays(bubbles: list[str], input_chars: int) -> list[float]:
    """首条 1.2+0.02×对方字数（夹在 1.0~4.5），之后 0.6+0.09×本条字数，再 ±30%。"""
    delays: list[float] = []
    for index, bubble in enumerate(bubbles):
        if index == 0:
            base = min(4.5, max(1.0, 1.2 + 0.02 * input_chars))
        else:
            base = 0.6 + 0.09 * len(bubble)
        delays.append(max(0.2, base * random.uniform(0.7, 1.3)))
    return delays
