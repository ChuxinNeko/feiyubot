"""健康检查。群里或网页对话发送 /ping 时回复 pong。"""


async def on_message(text: str, context: dict) -> str | None:
    if text.strip() == "/ping":
        return "pong"
    return None
