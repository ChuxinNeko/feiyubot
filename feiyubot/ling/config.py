"""从绫的配置存在 meta.ling，和原来的对话设置分开。"""

from __future__ import annotations

import json
from typing import Any

from feiyubot.core.store import Store

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "persona_name": "绫",
    "active_hours": "09:00-03:30",
    "reply_threshold": 35,
    "reply_window_seconds": 300,
    "max_bubbles_group": 2,
    "max_bubbles_private": 3,
    "allow_sleep": True,
    "wake_mode": "private_only",
    "forgetting_mode": "balanced",
    "inject_top_k": 5,
    "extra_admins": [],
    "include_group_role": False,
    "qzone_cookie": "",
    "qzone_allow_write": False,
    "qzone_uin": "",
    "proactive_enabled": False,
    "proactive_daily_cap": 3,
    "weather_city": "上海",
    "decision_log": True,
    "style_hint": True,
    "min_turns_before_sleep": 4,
    "latest_sleep": "02:30",
    "qzone_read_others": True,
}


def load(store: Store) -> dict[str, Any]:
    raw = store.get_meta("ling")
    data = dict(DEFAULTS)
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data.update({key: loaded[key] for key in DEFAULTS if key in loaded})
    return load_from_dict(data)


def save(store: Store, updates: dict[str, Any]) -> dict[str, Any]:
    current = load(store)
    for key, value in updates.items():
        if key in DEFAULTS:
            current[key] = value
    normalized = load_from_dict(current)
    store.set_meta("ling", json.dumps(normalized, ensure_ascii=False))
    return normalized


def load_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update({key: data[key] for key in DEFAULTS if key in data})
    merged["reply_threshold"] = max(0, min(100, int(merged["reply_threshold"])))
    merged["inject_top_k"] = max(0, min(20, int(merged["inject_top_k"])))
    merged["max_bubbles_group"] = max(1, min(5, int(merged["max_bubbles_group"])))
    merged["max_bubbles_private"] = max(1, min(6, int(merged["max_bubbles_private"])))
    if merged["forgetting_mode"] not in {"off", "dream", "balanced", "ebbinghaus"}:
        merged["forgetting_mode"] = "balanced"
    if merged["wake_mode"] not in {"private_only", "both", "never"}:
        merged["wake_mode"] = "private_only"
    merged["extra_admins"] = [str(item) for item in merged["extra_admins"] if str(item).strip()]
    merged["enabled"] = bool(merged["enabled"])
    merged["allow_sleep"] = bool(merged["allow_sleep"])
    merged["include_group_role"] = bool(merged["include_group_role"])
    merged["qzone_allow_write"] = bool(merged["qzone_allow_write"])
    merged["proactive_enabled"] = bool(merged["proactive_enabled"])
    merged["decision_log"] = bool(merged["decision_log"])
    merged["style_hint"] = bool(merged["style_hint"])
    merged["qzone_read_others"] = bool(merged["qzone_read_others"])
    merged["min_turns_before_sleep"] = max(1, min(30, int(merged["min_turns_before_sleep"])))
    merged["proactive_daily_cap"] = max(0, min(20, int(merged["proactive_daily_cap"])))
    merged["latest_sleep"] = str(merged["latest_sleep"] or "")
    return merged
