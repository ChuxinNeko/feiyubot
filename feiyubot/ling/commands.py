"""/绫 指令。网页里已登录的人算管理员；群里只认额外名单，群主默认不算。"""

from __future__ import annotations

HELP = (
    "/绫 状态 —— 看运行状态\n"
    "/绫 记忆 <词> —— 翻记忆\n"
    "/绫 记住 <内容> —— 手动记一条\n"
    "/绫 忘掉 <词> —— 忘掉相关记忆\n"
    "/绫 空间 看 —— 看空间动态\n"
    "/绫 空间 发 <内容> —— 发一条说说\n"
    "/绫 日记 —— 看最近一篇\n"
    "/绫 兼容 —— 看哪些能力自己在做\n"
    "/绫 签名 <内容> —— 改个性签名\n"
    "/绫 名片 <内容> —— 改本群名片\n"
    "/绫 调试 开/关 —— 决策日志"
)


def parse(text: str) -> list[str] | None:
    raw = (text or "").strip()
    if raw.startswith("/绫"):
        body = raw[2:]
    elif raw.startswith("/ling"):
        body = raw[4:]
    else:
        return None
    return [part for part in body.strip().split() if part]
