"""订阅匹配纯函数测试

测试范围（全部不依赖数据库，直接 import 被测函数）：
- normalize_keywords：用户输入的关键词清洗
- matched_keywords：命中关键词回传（前端「命中：xxx」）
- match_article：话题 OR 关键词的匹配判定

DB 相关的 fanout_new_article / backfill_feed 不在 pytest 覆盖范围内：
本仓库 tests/ 下没有 conftest.py 也没有测试库，这是既定约定。
这两个函数是纯函数的薄封装，靠演示页和 /docs 手工验证。
"""
from __future__ import annotations

from app.services.subscription import (
    MAX_KEYWORDS,
    match_article,
    matched_keywords,
    normalize_keywords,
)


class TestNormalizeKeywords:
    def test_strips_and_keeps_order(self) -> None:
        assert normalize_keywords(["  考研 ", "选课"]) == ["考研", "选课"]

    def test_dedupes_case_insensitively_keeping_first(self) -> None:
        # 保留用户第一次输入的原样大小写
        assert normalize_keywords(["API", "api", "Api"]) == ["API"]

    def test_collapses_inner_whitespace(self) -> None:
        assert normalize_keywords(["转 专业"]) == ["转 专业"]

    def test_drops_single_char_keywords(self) -> None:
        # 单字会命中几乎一切，直接丢弃
        assert normalize_keywords(["奖", "考研"]) == ["考研"]

    def test_drops_too_broad_words(self) -> None:
        # 泛词黑名单：这些词单独出现会淹掉整个订阅流
        assert normalize_keywords(["通知", "公告", "学院"]) == []
        assert normalize_keywords(["通知", "奖学金"]) == ["奖学金"]

    def test_drops_overlong_keywords(self) -> None:
        assert normalize_keywords(["一" * 33]) == []
        assert normalize_keywords(["一" * 32]) == ["一" * 32]

    def test_caps_at_max_keywords(self) -> None:
        raw = [f"关键词{i:02d}" for i in range(MAX_KEYWORDS + 5)]
        assert len(normalize_keywords(raw)) == MAX_KEYWORDS

    def test_handles_none_and_empty(self) -> None:
        assert normalize_keywords(None) == []
        assert normalize_keywords([]) == []
        assert normalize_keywords(["", "   "]) == []


class TestMatchedKeywords:
    def test_hits_in_title(self) -> None:
        assert matched_keywords(
            title="关于奖学金評定的通知", content="", keywords=["奖学金"]
        ) == ["奖学金"]

    def test_hits_in_content_only(self) -> None:
        assert matched_keywords(
            title="公告", content="本次选课时间为周一", keywords=["选课"]
        ) == ["选课"]

    def test_case_insensitive_for_latin(self) -> None:
        assert matched_keywords(
            title="API 接口说明", content="", keywords=["api"]
        ) == ["api"]

    def test_returns_all_hits(self) -> None:
        got = matched_keywords(
            title="考研讲座", content="面向考研学生，涉及选课", keywords=["考研", "选课", "实习"]
        )
        assert got == ["考研", "选课"]

    def test_no_hit_returns_empty(self) -> None:
        assert matched_keywords(title="社团招新", content="", keywords=["考研"]) == []

    def test_handles_none_fields(self) -> None:
        assert matched_keywords(title=None, content=None, keywords=["考研"]) == []
        assert matched_keywords(title="考研", content="x", keywords=None) == []

    def test_keyword_not_split_into_bigrams(self) -> None:
        # 本模块最关键的一条设计断言：
        # "四六级" 是完整词，不应该拆出 "六级" 去命中《英语六级考试报名》。
        # 直接子串匹配天然满足；若改用 retrieval._tokenize 的 bi-gram 就会误命中。
        assert matched_keywords(
            title="全国大学英语六级考试报名通知", content="", keywords=["四六级"]
        ) == []
        # 而用户明确填 "六级" 时应当命中
        assert matched_keywords(
            title="全国大学英语六级考试报名通知", content="", keywords=["六级"]
        ) == ["六级"]


class TestMatchArticle:
    def test_topic_hit(self) -> None:
        assert match_article(
            title="随便什么标题",
            content="正文",
            category="学业",
            topics=["学业", "就业"],
            keywords=[],
        )

    def test_topic_miss_but_keyword_hit(self) -> None:
        # OR 语义：话题没选中，但关键词命中，也要推
        assert match_article(
            title="选调生招录公告",
            content="",
            category="就业",
            topics=["学业"],
            keywords=["选调生"],
        )

    def test_topic_hit_but_keyword_miss(self) -> None:
        # OR 语义：选了学业话题，学业类文章全推，不要求关键词也命中
        assert match_article(
            title="选课通知",
            content="",
            category="学业",
            topics=["学业"],
            keywords=["考研"],
        )

    def test_neither_hits(self) -> None:
        assert not match_article(
            title="社团招新",
            content="",
            category="活动",
            topics=["学业"],
            keywords=["考研"],
        )

    def test_empty_subscription_matches_nothing(self) -> None:
        # 话题和关键词都为空 = 还没设置订阅，不该推送全部文章
        assert not match_article(
            title="任意标题",
            content="任意正文",
            category="学业",
            topics=[],
            keywords=[],
        )
        assert not match_article(
            title="任意标题", content="", category="学业", topics=None, keywords=None
        )

    def test_blank_category_never_matches_topic(self) -> None:
        # category 缺失的文章不应因为 topics 里恰好有 "" 而命中
        assert not match_article(
            title="", content="", category="", topics=[""], keywords=[]
        )

    def test_keyword_only_subscription_ignores_category(self) -> None:
        assert match_article(
            title="考研经验分享",
            content="",
            category="活动",  # 分类不在任何话题里，但没选话题
            topics=[],
            keywords=["考研"],
        )
