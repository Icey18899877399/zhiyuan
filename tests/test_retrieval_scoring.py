"""检索相关纯函数测试

测试范围：
- time_decay_score：M2 核心打分公式
- _tokenize：关键词降级路径用的中英文分词
- _snippet：摘要截取
- _build_embed_input：爬虫入库前拼装的 embedding 输入
"""
from __future__ import annotations

import math

import pytest

from app.crawler.base import _build_embed_input
from app.services.retrieval import _snippet, _tokenize, time_decay_score


class TestTimeDecayScore:
    def test_zero_age_returns_cos_sim(self) -> None:
        # 当 age=0，衰减系数 exp(0)=1，分数 == 余弦相似度
        assert time_decay_score(0.8, 0.0, decay_lambda=0.05) == pytest.approx(0.8)

    def test_decay_decreases_with_age(self) -> None:
        # 越老分数越低
        s1 = time_decay_score(0.8, 0.0, decay_lambda=0.05)
        s2 = time_decay_score(0.8, 7.0, decay_lambda=0.05)
        s3 = time_decay_score(0.8, 30.0, decay_lambda=0.05)
        assert s1 > s2 > s3

    def test_half_life_about_14_days_at_lambda_005(self) -> None:
        # 默认 λ=0.05 → 半衰期 ln(2)/0.05 ≈ 13.86 天
        # 14 天时分数应衰减到约 50%
        full = time_decay_score(1.0, 0.0, decay_lambda=0.05)
        half = time_decay_score(1.0, 14.0, decay_lambda=0.05)
        ratio = half / full
        assert 0.48 < ratio < 0.52

    def test_negative_age_clamped_to_zero(self) -> None:
        # 未来日期（age<0）不应给一个超过 cos_sim 的分数
        score = time_decay_score(0.8, -5.0, decay_lambda=0.05)
        assert score == pytest.approx(0.8)

    def test_lambda_higher_means_faster_decay(self) -> None:
        # λ 越大，14 天后分数越低
        s_lo = time_decay_score(1.0, 14.0, decay_lambda=0.05)
        s_hi = time_decay_score(1.0, 14.0, decay_lambda=0.10)
        assert s_hi < s_lo
        # λ=0.10 时 14 天 ≈ exp(-1.4) ≈ 0.247
        assert s_hi == pytest.approx(math.exp(-1.4), rel=1e-6)

    def test_cos_sim_zero_means_zero_score(self) -> None:
        assert time_decay_score(0.0, 5.0, decay_lambda=0.05) == 0.0


class TestTokenize:
    def test_chinese_bigrams(self) -> None:
        tokens = _tokenize("辅修招生通知")
        assert "辅修" in tokens
        assert "招生" in tokens

    def test_english_words(self) -> None:
        tokens = _tokenize("hello DeepSeek API")
        assert "hello" in tokens
        assert "deepseek" in tokens  # 小写化
        assert "api" in tokens

    def test_stopwords_filtered(self) -> None:
        tokens = _tokenize("最近有什么活动呢")
        # "最近"、"什么" 是停用 bi-gram；不应出现
        assert "最近" not in tokens
        assert "什么" not in tokens
        # "活动" 应保留
        assert "活动" in tokens

    def test_max_8_tokens(self) -> None:
        # 长查询不会爆 OR 链
        tokens = _tokenize("学业活动党团就业行政辅修招生选课考试")
        assert len(tokens) <= 8


class TestSnippet:
    def test_snippet_includes_hit_token(self) -> None:
        content = "前文一些内容" + "x" * 200 + "辅修招生录取名单" + "y" * 200
        out = _snippet(content, ["辅修"], radius=10)
        assert "辅修" in out

    def test_snippet_truncates_long_no_hit(self) -> None:
        content = "x" * 500
        out = _snippet(content, [], radius=10)
        assert len(out) <= 210  # 200 字 + 省略号

    def test_snippet_empty_content(self) -> None:
        assert _snippet("", ["辅修"]) == ""


class TestBuildEmbedInput:
    def test_title_duplicated_for_weight(self) -> None:
        # 标题重复一次以放大权重
        out = _build_embed_input("辅修招生通知", "正文一行")
        assert out.count("辅修招生通知") == 2

    def test_body_truncated(self) -> None:
        long_content = "字" * 5000
        out = _build_embed_input("标题", long_content)
        # 标题部分约 4 + 4 + 4 字（含分隔），正文截到 1500 字
        # 总长度上限约 1500 + 标题 * 2 + 分隔
        assert len(out) < 1600
