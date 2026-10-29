"""QQ 空间。没有 cookie 时说人话，不假装已经发出去。"""

from __future__ import annotations

import httpx

_LIST = "https://user.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6"
_PUBLISH = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"


def _missing() -> str:
    return "还没有空间登录态。在从绫页填 QQ 号和 cookie。"


async def feed_text(cookie: str, uin: str) -> str:
    if not cookie.strip() or not uin.strip():
        return _missing()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                _LIST,
                params={"uin": uin, "hostUin": uin, "num": 5, "pos": 0, "format": "json"},
                headers={"cookie": cookie, "referer": f"https://user.qzone.qq.com/{uin}"},
            )
        body = response.text[:500]
        if response.status_code != 200:
            return f"空间没打开：{response.status_code}"
        return body or "空间是空的"
    except Exception:
        return "空间这会儿没读到"


async def publish_text(cookie: str, uin: str, content: str) -> str:
    content = content.strip()
    if not content:
        return "要发什么"
    if not cookie.strip() or not uin.strip():
        return _missing()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                _PUBLISH,
                data={"con": content[:1000], "hostuin": uin, "format": "json"},
                headers={"cookie": cookie, "referer": f"https://user.qzone.qq.com/{uin}"},
            )
        if response.status_code != 200:
            return f"没发出去：{response.status_code}"
        return "说说已提交"
    except Exception:
        return "说说没发出去"
