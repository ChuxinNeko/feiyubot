"""本地 OpenAI 兼容接口，用来在没有真实密钥时演示记忆链路。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply(messages: list[dict]) -> str:
    blob = "\n".join(str(item.get("content") or "") for item in messages)
    system = messages[0].get("content", "") if messages else ""
    last = messages[-1].get("content", "") if messages else ""
    if "对话压缩器" in system:
        bits = []
        if "Morax" in blob:
            bits.append("用户叫 Morax")
        if "鱼丸" in blob:
            bits.append("猫叫鱼丸")
        return "；".join(bits) or "无新事实"
    if "长期记忆管理员" in system:
        lines = []
        if "Morax" in blob:
            lines.append("- 用户叫 Morax")
        if "鱼丸" in blob:
            lines.append("- 猫叫鱼丸")
        return "\n".join(lines) or "- 无"
    if "请只回复" in blob:
        return "在"
    if "猫" in last and "鱼丸" in blob:
        return "你养的猫叫鱼丸。"
    if ("名字" in last or "我叫" in last) and "Morax" in blob:
        return "你叫 Morax。"
    return f"我在。这次请求里能看到 {len(messages)} 条上下文。"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode())
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        text = reply(payload.get("messages") or [])
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": text}}]},
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock] {self.address_string()} {fmt % args}")


def serve(port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock openai http://127.0.0.1:{port}/v1/chat/completions")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
