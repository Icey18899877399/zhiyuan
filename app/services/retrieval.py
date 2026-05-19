"""文章检索（MVP：Postgres ILIKE 关键词匹配）

策略：
1. 把 question 切成关键词（按空白、标点切，过滤短词与停用词）
2. 用每个关键词命中标题或正文，按命中次数排序
3. 可选 category 过滤（对应前端 agent tab）
4. 回退：若关键词全 miss，按 category + 最新发布时间取 top_k

之后升级到 Chroma + embedding 时只需替换本文件，API 层无需改动。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article

_STOPWORDS = {
    # 单字
    "的", "了", "是", "我", "你", "他", "她", "它", "这", "那", "和", "与",
    "在", "有", "没", "也", "都", "就", "吗", "呢", "啊", "吧", "请", "想",
    "能", "会", "要", "把", "被", "给", "对", "为", "从", "到", "向", "及",
    # 常见停用 bi-gram（避免污染检索）
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

# 含此集合中任意字符的 bi-gram 视为低价值，直接丢弃
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
    """中文用 bi-gram、英文按词切，过滤停用词，最多 8 个 token。"""
    text = text or ""
    seen: set[str] = set()
    tokens: list[str] = []

    # 1) 拉丁词 / 标识符
    for m in _LATIN_RE.finditer(text):
        t = m.group().lower()
        if len(t) < 2 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        tokens.append(t)

    # 2) 连续 CJK 段：取整段（短）+ 所有相邻 bi-gram
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

    return tokens[:8]  # 防止 SQL OR 链爆炸


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


async def search_articles(
    db: AsyncSession,
    question: str,
    *,
    category: str | None = None,
    top_k: int = 5,
) -> list[RetrievedArticle]:
    tokens = _tokenize(question)

    base = select(Article)
    if category:
        base = base.where(Article.category == category)

    if not tokens:
        # 兜底：按最新发布时间取 top_k
        stmt = base.order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        ).limit(top_k)
        rows = (await db.execute(stmt)).scalars().all()
        return [_to_retrieved(a, tokens) for a in rows]

    # 命中数评分：每个 token 命中标题 +2，命中正文 +1
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
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        # 关键词全 miss，退化到时间序
        stmt = base.order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        ).limit(top_k)
        rows = (await db.execute(stmt)).scalars().all()

    return [_to_retrieved(a, tokens) for a in rows]


def _to_retrieved(a: Article, tokens: list[str]) -> RetrievedArticle:
    return RetrievedArticle(
        id=a.id,
        title=a.title,
        source=a.source,
        source_url=a.source_url,
        category=a.category,
        snippet=_snippet(a.content, tokens),
    )
