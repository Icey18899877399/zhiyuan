"""文章检索（M2 升级版）

主路径：pgvector 余弦相似度 + 时间衰减加权
    score = cos_sim * exp(-lambda * age_days)
    age 取 publish_time（缺失退回 crawled_at），单位"天"。
    lambda 由 settings.time_decay_lambda 控制：
        0.05 → 14 天半衰期（默认）
        0.10 → 7 天半衰期

降级路径：关键词 ILIKE + bi-gram（M1 之前的实现，原样保留）
    - EMBEDDING_PROVIDER=disabled
    - embedding 服务调用失败
    - question 本身无法被编码（空串等）
    - 库里所有 articles.embedding 都为空（早期数据 + backfill 没跑）

对外 API 与之前完全一致：search_articles(db, question, category, top_k)。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Article
from app.services import embedding as emb

_STOPWORDS = {
    # 单字
    "的", "了", "是", "我", "你", "他", "她", "它", "这", "那", "和", "与",
    "在", "有", "没", "也", "都", "就", "吗", "呢", "啊", "吧", "请", "想",
    "能", "会", "要", "把", "被", "给", "对", "为", "从", "到", "向", "及",
    # 常见停用 bi-gram
    "请问", "最近", "什么", "哪些", "怎么", "如何", "为何", "为什", "可以",
    "需要", "我们", "你们", "他们", "她们", "的话", "一下", "一些", "这个",
    "那个", "这些", "那些", "目前", "现在", "时候", "时间", "感觉", "觉得",
    "应该", "可能", "或者", "还有", "比如", "例如", "比方", "因此", "所以",
    # 英文
    "a", "an", "the", "is", "are", "was", "were", "of", "to", "for",
    "in", "on", "and", "or", "by", "with", "as", "at", "be", "this", "that",
}
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

_STOPWORD_CHARS = set(
    "的了是我你他她它这那和与在有没也都就吗呢啊吧请想能会要把被给对为从到向及"
    "最近些么哪如何怎可以需要你们我们他们她们应该可能或者还有比如例如时候时间"
    "什吧呀啦呵嗯哎哦唉嘛吧吧呢"
)


@dataclass
class RetrievedArticle:
    id: int
    title: str
    source: str
    source_url: str
    category: str
    snippet: str


def _tokenize(text: str) -> list[str]:
    """中文 bi-gram + 英文按词切；最多 8 个 token，过滤停用词。"""
    text = text or ""
    seen: set[str] = set()
    tokens: list[str] = []

    for m in _LATIN_RE.finditer(text):
        t = m.group().lower()
        if len(t) < 2 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        tokens.append(t)

    for m in _CJK_RUN_RE.finditer(text):
        run = m.group()
        if len(run) < 2:
            continue
        if 2 <= len(run) <= 4 and run not in seen and run not in _STOPWORDS:
            seen.add(run)
            tokens.append(run)
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg in _STOPWORDS or bg in seen:
                continue
            if any(ch in _STOPWORD_CHARS for ch in bg):
                continue
            seen.add(bg)
            tokens.append(bg)

    return tokens[:8]


def _snippet(content: str, tokens: list[str], radius: int = 80) -> str:
    if not content:
        return ""
    lower = content.lower()
    for tok in tokens:
        idx = lower.find(tok.lower())
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(content), idx + len(tok) + radius)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(content) else ""
            return prefix + content[start:end].replace("\n", " ") + suffix
    return content[:200].replace("\n", " ") + ("..." if len(content) > 200 else "")


def _to_retrieved(a: Article, tokens: list[str]) -> RetrievedArticle:
    return RetrievedArticle(
        id=a.id,
        title=a.title,
        source=a.source,
        source_url=a.source_url,
        category=a.category,
        snippet=_snippet(a.content, tokens),
    )


def time_decay_score(cos_sim: float, age_days: float, decay_lambda: float | None = None) -> float:
    """暴露成纯函数，便于单元测试

    cos_sim ∈ [-1, 1]（pgvector 实务上 ≥ 0），age_days ≥ 0
    """
    lam = decay_lambda if decay_lambda is not None else settings.time_decay_lambda
    age = max(0.0, age_days)
    return cos_sim * math.exp(-lam * age)


async def _search_by_vector(
    db: AsyncSession,
    query_vec: list[float],
    *,
    category: str | None,
    top_k: int,
) -> list[Article]:
    """主路径：向量检索 + 时间衰减加权排序"""
    age_seconds = func.extract(
        "epoch",
        func.now() - func.coalesce(Article.publish_time, Article.crawled_at),
    )
    age_days = age_seconds / 86400.0
    cos_sim = 1 - Article.embedding.cosine_distance(query_vec)
    score = cos_sim * func.exp(-settings.time_decay_lambda * age_days)

    stmt = select(Article).where(Article.embedding.is_not(None))
    if category:
        stmt = stmt.where(Article.category == category)
    stmt = stmt.order_by(score.desc()).limit(top_k)

    return list((await db.execute(stmt)).scalars().all())


async def _search_by_keyword(
    db: AsyncSession,
    tokens: list[str],
    *,
    category: str | None,
    top_k: int,
) -> list[Article]:
    """降级路径：关键词 ILIKE + bi-gram"""
    base = select(Article)
    if category:
        base = base.where(Article.category == category)

    if not tokens:
        stmt = base.order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        ).limit(top_k)
        return list((await db.execute(stmt)).scalars().all())

    score_expr = sum(
        (
            case((Article.title.ilike(f"%{t}%"), 2), else_=0)
            + case((Article.content.ilike(f"%{t}%"), 1), else_=0)
        )
        for t in tokens
    )
    keyword_filter = or_(
        *[Article.title.ilike(f"%{t}%") for t in tokens],
        *[Article.content.ilike(f"%{t}%") for t in tokens],
    )
    stmt = (
        base.where(keyword_filter)
        .order_by(
            score_expr.desc(),
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        )
        .limit(top_k)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    if not rows:
        stmt = base.order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        ).limit(top_k)
        rows = list((await db.execute(stmt)).scalars().all())

    return rows


async def search_articles(
    db: AsyncSession,
    question: str,
    *,
    category: str | None = None,
    top_k: int = 5,
) -> list[RetrievedArticle]:
    """主入口：先尝试向量检索；不可用时降级到关键词"""
    tokens = _tokenize(question)

    rows: list[Article] = []
    if emb.is_enabled() and question.strip():
        query_vec = await emb.embed_text(question)
        if query_vec is not None:
            rows = await _search_by_vector(
                db, query_vec, category=category, top_k=top_k
            )

    # 没有向量结果（embedding 关闭 / 库里无向量 / 全 miss）→ 关键词兜底
    if not rows:
        rows = await _search_by_keyword(
            db, tokens, category=category, top_k=top_k
        )

    return [_to_retrieved(a, tokens) for a in rows]
