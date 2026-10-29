"""把 OneBot 消息段收成模型能读的文本。"""

from __future__ import annotations

import json


def perceive(message) -> str:
    parts: list[str] = []
    for segment in message:
        kind = getattr(segment, "type", "")
        data = getattr(segment, "data", {}) or {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "at":
            parts.append(f"@{data.get('qq')}")
        elif kind == "image":
            parts.append("[图片]")
        elif kind == "record":
            parts.append("[语音]")
        elif kind == "reply":
            parts.append(f"[引用 {data.get('id')}]")
        elif kind == "json":
            parts.append(_card(str(data.get("data") or "")))
        elif kind == "forward":
            parts.append("[合并转发]")
        elif kind:
            parts.append(f"[{kind}]")
    return "".join(parts).strip()


def render_forward(nodes, *, depth: int = 0) -> str:
    """展开合并转发。说话人是记录里的人，不是正在跟机器人说话的那一个。"""
    if depth > 2 or not isinstance(nodes, list):
        return ""
    lines: list[str] = []
    for node in nodes[:60]:
        if not isinstance(node, dict):
            continue
        sender = node.get("sender") if isinstance(node.get("sender"), dict) else {}
        name = str((sender or {}).get("nickname") or (sender or {}).get("card") or node.get("user_id") or "某人")
        content = node.get("content")
        if content is None:
            content = node.get("message")
        if isinstance(content, list):
            text = _plain_segments(content)
            nested = [item for item in content if isinstance(item, dict) and item.get("type") == "forward"]
            for item in nested:
                inner = render_forward(item.get("content") or [], depth=depth + 1)
                if inner:
                    text = (text + "\n" + inner).strip()
        else:
            text = str(content or node.get("raw_message") or "")
        text = text.strip()
        if text:
            lines.append(f"{name}：{text}")
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > 1200:
        body = body[:400].rstrip() + "\n…\n" + body[-400:].lstrip()
    return "【合并转发，说话人是记录里的人，不是当前用户】\n" + body


def render_quote(sender: str, text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    who = sender.strip() or "某人"
    return f"【引用，作者是{who}，不是当前这句话的说话人】{body[:500]}"


def _plain_segments(segments) -> str:
    parts: list[str] = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "image":
            parts.append("[图片]")
        elif kind == "record":
            parts.append("[语音]")
        elif kind == "at":
            parts.append(f"@{data.get('qq')}")
        elif kind and kind != "forward":
            parts.append(f"[{kind}]")
    return "".join(parts).strip()


def _card(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "[卡片]"
    meta = payload.get("meta") if isinstance(payload, dict) else None
    title = ""
    if isinstance(meta, dict):
        for value in meta.values():
            if isinstance(value, dict) and value.get("title"):
                title = str(value["title"])
                break
    prompt = ""
    if isinstance(payload, dict):
        prompt = str(payload.get("prompt") or "")
    text = title or prompt
    return f"[卡片] {text}" if text else "[卡片]"
