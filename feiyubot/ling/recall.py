"""分级记忆的去重、遗忘和召回。只从用户说过的话里取事实。"""

from __future__ import annotations

from datetime import datetime, timezone

from feiyubot.core.store import Store
from feiyubot.ling.memory_level import STRENGTH, bigram_score, retention

_NEGATION = ("不是", "并不是", "别再", "不要再", "再也不是", "别提了")


def remember(
    store: Store,
    *,
    scope: str,
    subject: str,
    content: str,
    level: int,
    tags: list[str],
) -> int:
    content = content.strip()[:500]
    for atom in store.list_ling_atoms(subject=subject, limit=40):
        score = bigram_score(content, str(atom["content"]))
        if score >= 0.86:
            if level > int(atom["level"]):
                store.set_ling_atom_level(int(atom["id"]), level, STRENGTH.get(level, 0.65))
            store.touch_ling_atom(int(atom["id"]))
            return int(atom["id"])
        if 0.6 <= score < 0.86 and any(word in content for word in _NEGATION):
            store.archive_ling_atom(int(atom["id"]))
    return store.add_ling_atom(
        scope=scope,
        subject=subject,
        content=content,
        level=level,
        tags=tags,
        strength=STRENGTH.get(level, 0.65),
    )


def decay_atoms(store: Store, *, mode: str, now: datetime | None = None) -> int:
    """保留率掉到很低就归档。同一天再跑一遍，结果一样。"""
    moment = now or datetime.now(timezone.utc)
    archived = 0
    for atom in store.list_ling_atoms(limit=500):
        level = int(atom["level"])
        if level <= 0:
            continue
        stamp = str(atom.get("last_hit_at") or atom.get("created_at") or "")
        try:
            seen = datetime.fromisoformat(stamp)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        days = max(0.0, (moment - seen).total_seconds() / 86400)
        keep = retention(level, days, mode=mode, hits=int(atom.get("hits") or 0))
        if keep < 0.12:
            store.archive_ling_atom(int(atom["id"]))
            archived += 1
    return archived


def decay_if_due(store: Store, mode: str, today: str) -> int:
    if store.get_meta("ling_decay_day") == today:
        return 0
    count = decay_atoms(store, mode=mode)
    store.set_meta("ling_decay_day", today)
    return count


def should_inject(atom: dict, query: str, now: datetime) -> bool:
    score = bigram_score(query, str(atom.get("content") or ""))
    stamp = str(atom.get("injected_at") or "")
    if not stamp or score >= 0.45:
        return True
    try:
        seen = datetime.fromisoformat(stamp)
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    if (now - seen).total_seconds() >= 24 * 3600:
        return True
    return False
