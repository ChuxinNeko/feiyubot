"""记忆等级和遗忘曲线。保留率按「距上次被想起的天数」现算，重复结算结果一样。"""

from __future__ import annotations

import math

LEVEL_NAMES = {0: "不可忘", 1: "随口", 2: "细节", 3: "平常事实", 4: "在意的事", 5: "关键"}
STRENGTH = {0: 1.0, 1: 0.35, 2: 0.5, 3: 0.65, 4: 0.82, 5: 0.95}
FLOOR = {"identity": 4, "preference": 4}
CAP = {"routine": 2, "transient": 1}
BOOST = {"promise": 1, "user_stress": 1, "emotion_high": 1}
HARD = {"taboo": 0, "milestone": 5}
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("taboo", ("不许", "别碰", "不能提", "别提", "禁区", "底线")),
    ("milestone", ("第一次", "纪念日", "一周年", "刚认识你那天")),
    ("identity", ("我叫", "我的名字", "我是做", "我住在", "我生日", "我今年")),
    ("preference", ("我最喜欢", "我最讨厌", "受不了", "我超爱", "我根本不吃")),
    ("promise", ("约定", "答应", "说好", "欠你", "下次一起", "约好")),
    ("user_stress", ("记住", "别忘了", "很重要", "一定要", "千万")),
    ("emotion_high", ("崩溃", "哭", "难受死了", "气死", "开心死", "睡不着")),
    ("transient", ("今天", "刚才", "现在", "路上", "等下", "马上到", "这周")),
    ("routine", ("早安", "晚安", "在吗", "吃了吗", "哈哈", "在干嘛", "好的", "嗯嗯")),
]
DAILY_KEEP = {"dream": {1: 0.70, 2: 0.82, 3: 0.90, 4: 0.96, 5: 0.99}}
S_BASE = {1: 3, 2: 8, 3: 18, 4: 45, 5: 120}
S_GROWTH = {1: 1.4, 2: 1.4, 3: 1.5, 4: 1.6, 5: 1.8}
AFFINITY_STAGES = ["陌生", "眼熟", "熟人", "朋友", "亲近", "交心"]
AFFINITY_THRESHOLDS = [0, 100, 250, 450, 650, 850]


def rule_tags(text: str) -> list[str]:
    hits = [tag for tag, words in RULES if any(word in (text or "") for word in words)]
    if "routine" in hits and any(tag in hits for tag in ("promise", "taboo", "identity", "milestone")):
        hits.remove("routine")
    return hits


def judge_level(text: str, *, base: int = 3, stage: int | None = None) -> tuple[int, list[str]]:
    tags = rule_tags(text)
    for tag, fixed in HARD.items():
        if tag in tags:
            return fixed, tags
    level = max(1, min(5, int(base)))
    floor, cap = 1, 5
    for tag in tags:
        if tag in FLOOR:
            floor = max(floor, FLOOR[tag])
        if tag in CAP:
            cap = min(cap, CAP[tag])
        if tag in BOOST:
            level += BOOST[tag]
    level = max(floor, min(cap, level))
    if stage is not None:
        level = max(floor, min(cap, max(1, min(5, level + int(round((stage - 2) * 0.6))))))
    return level, tags


def retention(level: int, days: float, *, mode: str = "balanced", hits: int = 0) -> float:
    level = max(0, min(5, int(level)))
    if level == 0 or mode == "off":
        return 1.0
    days = max(0.0, float(days))
    dream = max(0.02, min(1.0, DAILY_KEEP["dream"].get(level, 0.9) ** days))
    if mode == "dream":
        return dream
    stability = S_BASE.get(level, 7) * min(8.0, S_GROWTH.get(level, 1.4) ** max(0, int(hits)))
    ebbinghaus = max(0.02, min(1.0, math.exp(-days / max(0.2, stability))))
    if mode == "ebbinghaus":
        return ebbinghaus
    return max(0.02, min(1.0, (dream + ebbinghaus) / 2.0))


def affinity_stage(score: float) -> int:
    stage = 0
    for index, threshold in enumerate(AFFINITY_THRESHOLDS):
        if score >= threshold:
            stage = index
    return stage


def bigram_score(query: str, text: str) -> float:
    def grams(value: str) -> set[str]:
        compact = "".join(value.split())
        if len(compact) < 2:
            return {compact} if compact else set()
        return {compact[i : i + 2] for i in range(len(compact) - 1)}

    left, right = grams(query), grams(text)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
