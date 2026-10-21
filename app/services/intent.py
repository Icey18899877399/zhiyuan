"""意图识别与专家路由。

规则优先完成可解释的高置信度识别；低置信度时可调用 LLM 分类回退。
所有外部分类结果都会经过本地白名单校验。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from app.config import settings
from app.services.deepseek import chat_completion

RouteMode = Literal["auto", "manual"]
IntentSource = Literal["manual", "rules", "llm"]

VALID_CATEGORIES = frozenset({"学业", "活动", "党团", "就业", "其他"})

EXPERT_BY_CATEGORY = {
    "学业": "academic",
    "活动": "activity",
    "党团": "party",
    "就业": "career",
    "其他": "admin",
}

# 规则优先保证高区分度词命中；同一领域多个词会提高置信度。
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "学业": (
        "选课",
        "考试",
        "成绩",
        "学位",
        "教务",
        "学分",
        "毕业",
        "保研",
        "考研",
        "学籍",
        "课程",
        "课表",
        "答辩",
        "开题",
        "中期",
        "推免",
        "重修",
        "奖学金",
        "绩点",
    ),
    "活动": (
        "活动",
        "讲座",
        "报告会",
        "沙龙",
        "比赛",
        "赛事",
        "嘉宾",
        "展览",
        "工作坊",
        "论坛",
        "颁奖",
        "公开课",
        "招新",
        "报名",
        "活动时间",
        "运动会",
    ),
    "党团": (
        "党支部",
        "团支部",
        "党课",
        "团课",
        "党员",
        "团员",
        "组织生活",
        "主题教育",
        "党建",
        "团委",
        "学生会",
        "学生干部",
        "团日",
        "党日",
        "党团",
        "入党",
        "入团",
    ),
    "就业": (
        "招聘",
        "实习",
        "宣讲会",
        "校招",
        "求职",
        "简历",
        "应聘",
        "offer",
        "用人单位",
        "就业",
        "招录",
        "岗位",
        "笔试",
        "面试",
        "档案",
        "户口",
    ),
    "其他": (
        "行政",
        "请假",
        "证明",
        "盖章",
        "宿舍",
        "财务",
        "报销",
        "办理",
        "材料提交",
        "证件",
        "服务大厅",
        "校园卡",
        "一卡通",
    ),
}


@dataclass(frozen=True)
class IntentResult:
    category: str | None
    expert: str
    confidence: float
    categories: tuple[str, ...] = ()
    experts: tuple[str, ...] = ()
    matched_keywords: tuple[str, ...] = ()
    source: IntentSource = "rules"
    warnings: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return "".join((text or "").lower().split())


def classify_intent(question: str) -> IntentResult:
    """根据问题返回一个或多个意图；无法判断时返回通用助手。"""
    text = _normalise(question)
    if not text:
        return IntentResult(category=None, expert="general", confidence=0.0)

    matches = {
        category: tuple(keyword for keyword in keywords if keyword.lower() in text)
        for category, keywords in INTENT_KEYWORDS.items()
    }
    scores = {
        category: sum(2 if len(keyword) >= 3 else 1 for keyword in keywords)
        for category, keywords in matches.items()
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    score = ordered[0][1]
    if score == 0:
        return IntentResult(category=None, expert="general", confidence=0.0)

    categories = tuple(category for category, category_score in ordered if category_score > 0)
    category = categories[0]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0
    margin = score - runner_up
    confidence = min(0.99, 0.55 + score * 0.08 + margin * 0.04)
    experts = tuple(EXPERT_BY_CATEGORY[item] for item in categories)
    return IntentResult(
        category=category,
        expert=experts[0],
        confidence=round(confidence, 3),
        categories=categories,
        experts=experts,
        matched_keywords=matches[category],
    )


def _parse_llm_result(raw: str) -> IntentResult | None:
    """解析并校验模型 JSON；允许模型包裹 markdown 代码块。"""
    text = raw.strip()
    fenced = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    if "categories" in payload:
        raw_categories = payload["categories"]
    elif "category" in payload:
        raw_categories = payload["category"]
    else:
        return None
    if "confidence" not in payload:
        return None
    raw_confidence = payload["confidence"]
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        return None
    try:
        confidence = float(raw_confidence)
    except OverflowError:
        return None
    if not math.isfinite(confidence):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    if not isinstance(raw_categories, list):
        return None

    categories = tuple(
        dict.fromkeys(
            category
            for category in raw_categories
            if isinstance(category, str) and category in VALID_CATEGORIES
        )
    )
    if not categories:
        if raw_categories:
            return None
        return IntentResult(category=None, expert="general", confidence=0.0, source="llm")

    experts = tuple(EXPERT_BY_CATEGORY[category] for category in categories)
    return IntentResult(
        category=categories[0],
        expert=experts[0],
        confidence=round(confidence, 3),
        categories=categories,
        experts=experts,
        source="llm",
    )


async def _classify_by_llm(question: str) -> IntentResult | None:
    system_prompt = (
        "你是校园信息问答系统的意图分类器。只输出 JSON，不要输出解释。"
        "categories 只能从 学业、活动、党团、就业、其他 中选择一个或多个；"
        "无关问题返回空数组。confidence 为 0 到 1 的数字。"
    )
    user_prompt = (
        "请识别下面问题涉及的领域，复合问题可以返回多个领域。"
        '输出格式：{"categories":["学业"],"confidence":0.86}\n'
        f"问题：{question}"
    )
    try:
        raw = await chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=128,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"LLM 意图识别失败，回退规则结果：{exc}")
        return None
    return _parse_llm_result(raw)


async def resolve_intent(
    question: str,
    *,
    selected_category: str | None,
    route_mode: RouteMode,
) -> IntentResult:
    """手动模式保持旧行为，自动模式按规则优先、LLM 兜底。"""
    if route_mode == "manual":
        if selected_category in VALID_CATEGORIES:
            return IntentResult(
                category=selected_category,
                expert=EXPERT_BY_CATEGORY[selected_category],
                confidence=1.0,
                categories=(selected_category,),
                experts=(EXPERT_BY_CATEGORY[selected_category],),
                source="manual",
            )
        return IntentResult(category=None, expert="general", confidence=0.0, source="manual")

    rule_result = classify_intent(question)
    if (
        rule_result.confidence >= settings.intent_confidence_threshold
        or not settings.deepseek_api_key
    ):
        return rule_result

    llm_result = await _classify_by_llm(question)
    if llm_result is None:
        return IntentResult(
            category=rule_result.category,
            expert=rule_result.expert,
            confidence=rule_result.confidence,
            categories=rule_result.categories,
            experts=rule_result.experts,
            matched_keywords=rule_result.matched_keywords,
            source=rule_result.source,
            warnings=("大模型意图识别未能提供有效结果，已按关键词规则路由。",),
        )
    if llm_result.categories and llm_result.confidence < settings.intent_confidence_threshold:
        logger.info(
            "LLM 意图置信度低于阈值，使用通用路由："
            f"confidence={llm_result.confidence} "
            f"threshold={settings.intent_confidence_threshold}"
        )
        return IntentResult(
            category=None,
            expert="general",
            confidence=llm_result.confidence,
            source="llm",
        )
    return llm_result
