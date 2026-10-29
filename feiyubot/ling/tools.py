"""时间、天气、翻译、MC 状态、网页标题。任何一项失败都只返回人话，不把异常抛出去。"""

from __future__ import annotations

import re
import socket
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

_URL_RE = re.compile(r"https?://[^\s]+")


def current_time_text(zone: str = "Asia/Shanghai") -> str:
    now = datetime.now(ZoneInfo(zone))
    week = "一二三四五六日"[now.weekday()]
    return now.strftime(f"%Y-%m-%d 星期{week} %H:%M")


async def weather_text(city: str) -> str:
    city = (city or "").strip() or "上海"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh"},
            )
            geo.raise_for_status()
            results = (geo.json() or {}).get("results") or []
            if not results:
                return f"没找到「{city}」的天气"
            hit = results[0]
            forecast = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": hit["latitude"],
                    "longitude": hit["longitude"],
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
            )
            forecast.raise_for_status()
            body = forecast.json()
            current = body.get("current") or {}
            daily = body.get("daily") or {}
            highs = daily.get("temperature_2m_max") or []
            lows = daily.get("temperature_2m_min") or []
            name = hit.get("name") or city
            temp = current.get("temperature_2m")
            extra = ""
            if highs and lows:
                extra = f"，今天 {lows[0]}~{highs[0]}°C"
            return f"{name}现在 {temp}°C{extra}"
    except Exception:
        return "天气这会儿没查到"


async def peek_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "这个地址打不开"
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(url, headers={"user-agent": "feiyubot"})
        match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
        title = re.sub(r"\s+", " ", match.group(1)).strip() if match else parsed.netloc
        return f"{title} · {parsed.netloc}"[:200]
    except Exception:
        return "网页没打开"


async def mc_status(host: str) -> str:
    host = host.strip()
    if not host or " " in host or len(host) > 80:
        return "服务器地址不像样"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"https://api.mcsrvstat.us/2/{host}")
            response.raise_for_status()
            body = response.json()
        if not body.get("online"):
            return f"{host} 现在不在线"
        players = body.get("players") or {}
        return f"{host} 在线 {players.get('online', 0)}/{players.get('max', '?')}"
    except Exception:
        try:
            socket.getaddrinfo(host.split(":")[0], None)
        except OSError:
            return "没解析到这个服务器"
        return "服务器状态没查到"


def allow_call(stamps: list[float], now: float, *, limit: int = 20, window: float = 60) -> tuple[bool, list[float]]:
    fresh = [item for item in stamps if now - item < window]
    if len(fresh) >= limit:
        return False, fresh
    fresh.append(now)
    return True, fresh


def maybe_tool(text: str) -> tuple[str, str] | None:
    raw = text or ""
    if any(word in raw for word in ("你的状态", "运行状态", "记忆几条", "你现在怎么样")):
        return ("status", "")
    if any(word in raw for word in ("几点", "几号", "星期几", "现在时间", "今天几")):
        return ("time", "")
    if "天气" in raw:
        city = "上海"
        matched = re.search(r"([\u4e00-\u9fff]{2,8})的?天气", raw)
        if matched:
            city = matched.group(1).removeprefix("查").removeprefix("看")
        return ("weather", city)
    if raw.startswith("翻译") or "翻译一下" in raw or raw.lower().startswith("translate"):
        payload = raw
        for prefix in ("翻译一下", "翻译", "translate"):
            if payload.lower().startswith(prefix):
                payload = payload[len(prefix) :]
                break
        return ("translate", payload.strip(" ：:"))
    if "服务器" in raw and ("mc" in raw.lower() or "我的世界" in raw):
        host = ""
        found = re.search(r"([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?)", raw)
        if found:
            host = found.group(1)
        return ("mc", host)
    found = _URL_RE.search(raw)
    if found and any(word in raw for word in ("看看", "打开", "这是什么", "链接")):
        return ("web", found.group(0).rstrip("，。"))
    return None
