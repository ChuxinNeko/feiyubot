"""真实拉起飞鱼，用 OneBot v11 反向 WebSocket 走一遍群回复，并在重启后确认还记得。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("FEIYU_PYTHON", "/tmp/feiyu-venv/bin/python")
SELF_ID = 10001
USER_ID = 20002
GROUP_ID = 30003


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _load_mock():
    spec = importlib.util.spec_from_file_location("mock_openai", ROOT / "scripts" / "mock_openai.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wait_health(port: int) -> None:
    deadline = time.time() + 30
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
            time.sleep(0.2)
    raise RuntimeError(f"飞鱼没有在 {port} 起来: {last}")


def _start_bot(port: int, data_dir: Path, log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "FEIYU_DATA_DIR": str(data_dir),
            "FEIYU_ADMIN_PASSWORD": "test-onebot",
            "ONEBOT_V11_ACCESS_TOKEN": "",
            "ONEBOT_V11_WS_URLS": "[]",
            "FEIYU_LING_NO_DELAY": "1",
        }
    )
    log = log_path.open("ab")
    return subprocess.Popen(
        [PYTHON, str(ROOT / "bot.py")],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _event(text: str, message_id: int, *, addressed: bool) -> dict:
    message: list[dict] = []
    if addressed:
        message.append({"type": "at", "data": {"qq": str(SELF_ID)}})
        text = " " + text
    message.append({"type": "text", "data": {"text": text}})
    return {
        "time": int(time.time()),
        "self_id": SELF_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": message_id,
        "user_id": USER_ID,
        "group_id": GROUP_ID,
        "font": 0,
        "raw_message": text,
        "message": message,
        "sender": {"user_id": USER_ID, "nickname": "Morax", "card": "Morax"},
    }


def _plain(params: dict) -> str:
    message = params.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "".join(
            str(segment.get("data", {}).get("text", ""))
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "text"
        )
    return str(message)


async def _roundtrip(port: int, events: list[tuple[dict, bool]]) -> list[str]:
    sent: list[str] = []
    async with websockets.connect(
        f"ws://127.0.0.1:{port}/onebot/v11/ws",
        additional_headers={"X-Self-ID": str(SELF_ID)},
        open_timeout=5,
    ) as ws:
        for event, expect_reply in events:
            await ws.send(json.dumps(event))
            found = await _collect(ws, expect_reply)
            sent.extend(found)
    return sent


async def _collect(ws, expect_reply: bool) -> list[str]:
    found: list[str] = []
    deadline = time.time() + (20 if expect_reply else 1.5)
    while time.time() < deadline:
        if expect_reply and found:
            return found
        remaining = deadline - time.time()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
        except TimeoutError:
            break
        data = json.loads(raw)
        action = data.get("action")
        echo = data.get("echo")
        if action == "get_group_info":
            body = {"group_id": GROUP_ID, "group_name": "陪伴群"}
        elif action in {"send_msg", "send_group_msg"}:
            found.append(_plain(data.get("params") or {}))
            body = {"message_id": 1}
        else:
            body = {}
        await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": body, "echo": echo}))
    if expect_reply and not found:
        raise AssertionError("群消息没有通过 OneBot 发出去")
    if not expect_reply and found:
        raise AssertionError(f"没被叫到却回复了: {found}")
    return found


def test_group_reply_survives_restart(tmp_path):
    mock = _load_mock()
    mock_port = _free_port()
    server = mock.serve(mock_port)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    log_path = tmp_path / "bot.log"
    port = _free_port()
    proc = _start_bot(port, data_dir, log_path)
    try:
        _wait_health(port)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            assert client.post("/api/login", json={"password": "test-onebot"}).status_code == 200
            created = client.post(
                "/api/providers",
                json={
                    "name": "演示",
                    "base_url": f"http://127.0.0.1:{mock_port}/v1",
                    "api_key": "demo",
                    "model": "demo",
                    "priority": 1,
                },
            )
            assert created.status_code == 200, created.text

        first = asyncio.run(
            _roundtrip(
                port,
                [
                    (_event("记住：群里的猫叫鱼丸", 1, addressed=False), False),
                    (_event("我的猫叫什么？", 2, addressed=True), True),
                ],
            )
        )
        assert first == ["你养的猫叫鱼丸"]

        _stop(proc)
        proc = _start_bot(port, data_dir, log_path)
        _wait_health(port)
        second = asyncio.run(_roundtrip(port, [(_event("我的猫叫什么？", 3, addressed=True), True)]))
        assert second == ["你养的猫叫鱼丸"]

        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            assert client.post("/api/login", json={"password": "test-onebot"}).status_code == 200
            detail = client.get(f"/api/sessions/group:{GROUP_ID}")
            assert detail.status_code == 200, detail.text
            body = detail.json()
            contents = [item["content"] for item in body["messages"]]
        assert any("记住：群里的猫叫鱼丸" in item for item in contents)
        assert sum("你养的猫叫鱼丸" in item for item in contents) == 2
        assert "鱼丸" in body["memory_notes"]
    except Exception:
        if log_path.exists():
            print(log_path.read_text(errors="replace")[-4000:])
        raise
    finally:
        _stop(proc)
        server.shutdown()
