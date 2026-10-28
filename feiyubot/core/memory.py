"""上下文组装、自动压缩和唤醒判断。

完整历史在数据库里。发给模型的是：人格 + 长期记忆 + 较早对话摘要 + 最近原文。
对话变长后才压缩，所以不会聊几句就把原文丢掉。
"""

from __future__ import annotations

from datetime import datetime

from feiyubot.core.models import ChatMessage, Persona, Session, Settings
from feiyubot.core.store import utcnow

COMPRESS_MARK = "对话压缩器"
MEMORY_MARK = "长期记忆管理员"

_COMMANDS = {
    "/reset",
    "/重置",
    "重置记忆",
    "清空记忆",
    "/memory",
    "/记忆",
    "查看记忆",
    "/help",
    "/帮助",
    "帮助",
    "/personas",
    "人格列表",
    "/ping",
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


def is_command(text: str) -> bool:
    raw = text.strip()
    lowered = raw.lower()
    if lowered in _COMMANDS or raw in _COMMANDS:
        return True
    if raw.startswith("/") or raw.startswith("切换人格") or raw.startswith("人格 "):
        return True
    return False


def parse_command(text: str) -> tuple[str, str] | None:
    raw = text.strip()
    lowered = raw.lower()
    if lowered in {"/reset", "/重置", "重置记忆", "清空记忆"}:
        return ("reset", "")
    if lowered in {"/memory", "/记忆", "查看记忆"}:
        return ("memory", "")
    if lowered in {"/help", "/帮助", "帮助"}:
        return ("help", "")
    if lowered in {"/personas", "人格列表"}:
        return ("persona", "")
    if raw.startswith("/persona"):
        return ("persona", raw[len("/persona") :].strip())
    if raw.startswith("切换人格"):
        return ("persona", raw[len("切换人格") :].strip())
    if raw.startswith("人格 "):
        return ("persona", raw[len("人格 ") :].strip())
    return None


def admission(settings: Settings, session: Session, kind: str) -> tuple[bool, str]:
    """群是否允许记入上下文。网页对话始终允许。"""

    if kind == "web":
        return True, "web"
    if not session.enabled:
        return False, "disabled"
    group_id = session.group_id or ""
    if group_id and group_id in set(settings.group_blacklist):
        return False, "blacklist"
    if settings.group_whitelist and group_id not in set(settings.group_whitelist):
        return False, "whitelist"
    return True, "ok"


def wants_reply(
    *,
    settings: Settings,
    session: Session,
    text: str,
    addressed: bool,
    kind: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """决定要不要开口。不开口时消息仍然留下，下次被叫到还能接上。"""

    if kind == "web":
        return True, "web"
    command = is_command(text)
    mode = session.wake_mode or settings.wake_mode
    if mode == "always":
        woken = True
    elif mode == "keyword":
        woken = addressed or any(word and word in text for word in settings.wake_words)
    else:
        woken = addressed
    if not woken and not command:
        return False, "wake"
    if not command and not addressed and session.last_reply_at and settings.min_interval_seconds > 0:
        try:
            previous = datetime.fromisoformat(session.last_reply_at)
        except ValueError:
            previous = None
        if previous is not None and (now or utcnow()) - previous < _seconds(settings.min_interval_seconds):
            return False, "interval"
    return True, "command" if command else "ok"


def _seconds(value: float):
    from datetime import timedelta

    return timedelta(seconds=value)


def pin_explicit_memory(notes: str, text: str) -> str:
    """用户明确说「记住」时，立刻写入长期记忆，不等待模型摘要。"""

    raw = " ".join(text.split())
    if "记住" not in raw:
        return notes
    line = raw[:180]
    bullet = f"- {line}"
    existing = notes.strip()
    if line in existing:
        return existing
    merged = (existing + "\n" + bullet).strip()
    return merged[:3000]


def local_summary(previous: str, messages: list[ChatMessage], *, limit: int = 3000) -> str:
    """模型压缩失败时的摘录。保留开头和结尾，避免最早的事实被截掉。"""

    lines: list[str] = []
    for message in messages:
        if message.notice:
            continue
        who = message.sender_name or ("飞鱼" if message.role == "assistant" else "用户")
        text = " ".join(message.content.split())
        if len(text) > 160:
            text = text[:160] + "…"
        lines.append(f"{who}: {text}")
    chunks = [previous.strip(), *lines]
    merged = "\n".join(chunk for chunk in chunks if chunk)
    if len(merged) <= limit:
        return merged
    half = max(200, limit // 2)
    return merged[:half] + "\n…\n" + merged[-half:]


def render_system(
    *,
    bot_name: str,
    persona: Persona | None,
    session: Session,
    knowledge: str,
) -> str:
    persona_text = persona.prompt.strip() if persona else ""
    if not persona_text:
        persona_text = f"你是{bot_name}，一个温柔的陪伴型伙伴。"
    where = "QQ 群" if session.kind == "group" else "网页对话"
    parts = [
        persona_text,
        (
            f"你正在{where}「{session.title}」里陪大家聊天。"
            "用自然的中文短句回复，像群里的朋友，不要客服腔，不要复述这段系统提示。"
            "长期记忆和较早摘要里的事都已经发生过，回答时要沿用；只有那里确实没有时才说不记得。"
        ),
    ]
    if knowledge.strip():
        parts.append("# 补充资料\n" + knowledge.strip()[:4000])
    if session.memory_notes.strip():
        parts.append("# 长期记忆\n" + session.memory_notes.strip())
    if session.summary.strip():
        parts.append("# 更早的对话摘要\n" + session.summary.strip())
    return "\n\n".join(parts)


def build_messages(system: str, recent: list[ChatMessage]) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    for item in recent:
        if item.notice:
            continue
        role = item.role if item.role in {"user", "assistant"} else "user"
        messages.append({"role": role, "content": item.content})
    return messages


def estimate_messages(messages: list[dict]) -> int:
    return sum(estimate_tokens(str(item.get("content") or "")) + 4 for item in messages)


def compression_prompt(summary: str, messages: list[ChatMessage]) -> list[dict]:
    transcript = []
    for item in messages:
        if item.notice:
            continue
        who = item.sender_name or item.role
        transcript.append(f"{who}: {item.content}")
    return [
        {
            "role": "system",
            "content": (
                f"你是{COMPRESS_MARK}。把「已有摘要」和「新增对话」合并成一份新的中文摘要。"
                "必须保留人名、昵称、称呼、偏好、约定、情绪、正在进行的话题和关键事实。"
                "不要寒暄，不要编造。控制在 800 字以内。"
            ),
        },
        {
            "role": "user",
            "content": f"已有摘要：\n{summary.strip() or '（无）'}\n\n新增对话：\n" + "\n".join(transcript),
        },
    ]


def memory_prompt(notes: str, messages: list[ChatMessage]) -> list[dict]:
    transcript = []
    for item in messages:
        if item.notice:
            continue
        who = item.sender_name or item.role
        transcript.append(f"{who}: {item.content}")
    return [
        {
            "role": "system",
            "content": (
                f"你是{MEMORY_MARK}。根据已有记忆和新增对话，输出更新后的记忆条目。"
                "每条一行，以「- 」开头。只保留稳定事实、关系和未完成的约定。"
                "删除已被纠正的内容。不要写寒暄原文。不超过 30 条。"
            ),
        },
        {
            "role": "user",
            "content": f"已有记忆：\n{notes.strip() or '（无）'}\n\n新增对话：\n" + "\n".join(transcript),
        },
    ]


HELP_TEXT = (
    "我是飞鱼。可以这样叫我：\n"
    "/help 查看说明\n"
    "/ping 检查我还在不在\n"
    "/memory 查看我记住的摘要\n"
    "/reset 清空这段对话的上下文\n"
    "切换人格 名字\n"
    "跟我说「记住：……」，我会立刻写进长期记忆。"
)
