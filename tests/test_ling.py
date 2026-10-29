"""从绫的纯逻辑：守卫、分句、打分、等级、遗忘和睡眠阶段。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from feiyubot.core.store import Store
from feiyubot.ling.express import Decider, clean_text, in_active_hours, split_bubbles
from feiyubot.ling.memory_level import judge_level, retention
from feiyubot.ling.night import stage_at, wake_chance
from feiyubot.ling.perceive import perceive, render_forward
from feiyubot.ling.recall import decay_atoms, remember
from feiyubot.ling.tools import allow_call


class _Seg:
    def __init__(self, kind, data):
        self.type = kind
        self.data = data


def test_guard_and_short_split():
    assert clean_text("好的。😊") == "好的"
    assert clean_text("真的吗？") == "真的吗？"
    assert split_bubbles("在的") == ["在的"]


def test_group_stays_quiet_until_named():
    decider = Decider()
    decider.observe("group:1", "今天好热")
    quiet = decider.decide(
        session_id="group:1",
        kind="group",
        text="今天好热",
        addressed=False,
        persona_name="绫",
        active=True,
    )
    assert quiet.should_reply is False
    named = decider.decide(
        session_id="group:1",
        kind="group",
        text="绫在吗",
        addressed=False,
        persona_name="绫",
        active=True,
    )
    assert named.should_reply is True
    private = decider.decide(
        session_id="web:1",
        kind="web",
        text="在吗",
        addressed=False,
        persona_name="绫",
    )
    assert private.should_reply is True


def test_levels_and_forgetting_are_stable():
    taboo, tags = judge_level("不许提这件事")
    assert taboo == 0 and "taboo" in tags
    identity, _ = judge_level("我叫小山")
    assert identity >= 4
    assert retention(0, 30) == 1.0
    assert retention(1, 10, mode="balanced") == retention(1, 10, mode="balanced")
    assert retention(1, 10, mode="balanced") < retention(5, 10, mode="balanced")


def test_sleep_stage_is_derived_from_time():
    sleep_at = 1_700_000_000
    early = stage_at(sleep_at, sleep_at + 60)
    deep = stage_at(sleep_at, sleep_at + 40 * 60)
    assert early and early["key"] == "n1"
    assert deep and deep["key"] == "n3"
    assert wake_chance(1) == 0.0
    assert wake_chance(2) > 0


def test_active_hours_cross_midnight():
    morning = time.strptime("2026-10-29 10:00", "%Y-%m-%d %H:%M")
    dawn = time.strptime("2026-10-29 04:00", "%Y-%m-%d %H:%M")
    assert in_active_hours("09:00-03:30", morning) is True
    assert in_active_hours("09:00-03:30", dawn) is False


def test_perceive_special_segments():
    text = perceive(
        [
            _Seg("at", {"qq": "1"}),
            _Seg("text", {"text": " 看这个"}),
            _Seg("image", {}),
            _Seg("record", {}),
            _Seg("json", {"data": '{"prompt":"哔哩哔哩"}'}),
        ]
    )
    assert "[图片]" in text and "[语音]" in text and "哔哩哔哩" in text


def test_forward_names_the_record_speakers():
    text = render_forward(
        [
            {"sender": {"nickname": "小山"}, "content": "猫叫鱼丸"},
            {"sender": {"nickname": "绫"}, "content": "知道了"},
        ]
    )
    assert "不是当前用户" in text
    assert "小山：猫叫鱼丸" in text


def test_similar_memory_is_reinforced(tmp_path):
    store = Store(tmp_path / "atoms.sqlite")
    first = remember(store, scope="user", subject="1", content="记住我叫小山住在上海", level=4, tags=["identity"])
    second = remember(store, scope="user", subject="1", content="记住我叫小山住在上海呀", level=4, tags=["identity"])
    assert first == second
    assert store.count_ling_atoms() == 1
    store.close()


def test_old_smalltalk_is_archived_and_taboo_stays(tmp_path):
    store = Store(tmp_path / "decay.sqlite")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    chatter = store.add_ling_atom(scope="user", subject="1", content="今天好热", level=1, tags=["transient"], strength=0.3)
    taboo = store.add_ling_atom(scope="user", subject="1", content="不许提这件事", level=0, tags=["taboo"], strength=1)
    store.retime_ling_atom(chatter, old)
    store.retime_ling_atom(taboo, old)
    assert decay_atoms(store, mode="dream") == 1
    assert store.count_ling_atoms() == 1
    assert decay_atoms(store, mode="dream") == 0
    store.close()


def test_tool_limit_is_twenty_a_minute():
    now = 1000.0
    stamps: list[float] = []
    for _ in range(20):
        ok, stamps = allow_call(stamps, now)
        assert ok
    blocked, _ = allow_call(stamps, now)
    assert blocked is False
