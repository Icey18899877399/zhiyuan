"""订阅匹配服务

把「新入库的文章」和「用户声明的关注方向」对上，命中就写一条 user_unread。

匹配语义 —— 话题 **或** 关键词：
    - 话题：article.category ∈ subscription.topics        （粗筛，精确匹配）
    - 关键词：kw 出现在 title 或 content 里（不区分大小写）  （精筛，子串匹配）
    两者任一命中即推送。话题和关键词**都为空**视为「还没设置」，不匹配任何文章。

为什么关键词不用 retrieval._tokenize 的 bi-gram：
    用户填的是完整词（"奖学金"），直接子串匹配可预期；
    而 bi-gram 会把"四六级"拆出"六级"，让《英语六级考试报名》这类通知误命中。

文件分两半：上半是**纯函数区**（不碰数据库、不依赖配置），可被 pytest 直接 import——
tests/ 下没有 conftest.py、没有测试库，三个现有测试文件全是纯函数测试，这是仓库既定约定。
下半是 DB 区，是纯函数的薄封装。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Article, Subscription, UserUnread

# 与 app/api/chat.py 的 VALID_AGENTS 一致，话题取值就这五类
CATEGORIES: tuple[str, ...] = ("学业", "活动", "党团", "就业", "其他")

MIN_KEYWORD_LEN = 2
MAX_KEYWORD_LEN = 32
MAX_KEYWORDS = 20

# 泛词黑名单：单独出现会命中几乎所有通知，把订阅流淹掉。
# 演示前引导用户填具体词（"奖学金"而不是"通知"）。
_TOO_BROAD = {
    "通知", "公告", "新闻", "动态", "学院", "学校", "大学", "学生", "老师",
    "关于", "有关", "进行", "开展", "组织", "工作", "活动", "相关", "要求",
}


# ───────────────────────── 纯函数区（可独立测试） ─────────────────────────


def normalize_keywords(raw: list[str] | None) -> list[str]:
    """清洗用户输入的关键词：去空白、丢过短/过泛词、去重（保序）、截断到上限。

    保留用户输入的原始大小写，只用小写做去重判断。
    """
    out: list[str] = []
    seen: set[str] = set()

    for item in raw or []:
        kw = " ".join(str(item).split())  # 折叠内部空白
        if len(kw) < MIN_KEYWORD_LEN or len(kw) > MAX_KEYWORD_LEN:
            continue
        if kw in _TOO_BROAD:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
        if len(out) >= MAX_KEYWORDS:
            break

    return out


def matched_keywords(
    *, title: str | None, content: str | None, keywords: list[str] | None
) -> list[str]:
    """返回真正命中的关键词（保留用户输入原样），用于前端展示「命中：考研、选课」。

    把匹配从黑盒变成可解释的——误命中时用户自己就能看懂原因。
    """
    haystack = f"{title or ''}\n{content or ''}".lower()
    return [kw for kw in (keywords or []) if kw.lower() in haystack]


def match_article(
    *,
    title: str | None,
    content: str | None,
    category: str | None,
    topics: list[str] | None,
    keywords: list[str] | None,
) -> bool:
    """判断一篇文章是否命中某份订阅。话题命中 **或** 关键词命中即 True。

    话题与关键词都为空 → False（未设置订阅不推送任何东西，而不是推送全部）。
    """
    if category and category in (topics or ()):
        return True
    return bool(matched_keywords(title=title, content=content, keywords=keywords))


# ────────────────────────────── DB 区 ──────────────────────────────


async def _enabled_subscriptions(session: AsyncSession) -> list[Subscription]:
    stmt = select(Subscription).where(Subscription.enabled.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def _insert_unread(session: AsyncSession, user_ids: list[int], article_id: int) -> int:
    """批量写未读。ON CONFLICT DO NOTHING 保证幂等。

    刻意用 DO NOTHING 而不是 DO UPDATE：已读的行不能被重新标成未读，
    否则用户每次改订阅，读过的通知会全部「复活」。
    """
    if not user_ids:
        return 0
    stmt = (
        pg_insert(UserUnread)
        .values(
            [{"user_id": uid, "article_id": article_id, "is_read": False} for uid in user_ids]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "article_id"])
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def fanout_new_article(session: AsyncSession, article: Article) -> int:
    """新文章入库后调用：对全部启用订阅做匹配，命中的用户各写一条未读。

    返回新增未读条数。

    用**调用方的 session**，跟着外层事务一起提交，不自己开 session——
    app/crawler/base.py 是每 5 条 commit 一次，另开会话会和它打架。
    调用方必须用 `async with session.begin_nested()` 把本函数包起来（SAVEPOINT），
    否则这里抛错会让整个事务进入 aborted 状态，把刚爬到的文章一起回滚掉。

    性能：一次 SELECT 取全部启用订阅，在内存里逐条匹配。
    演示量级（订阅 < 100、每天几十篇）无感。若订阅数上万，应改为
    入库只写 article，匹配交给独立的 APScheduler 任务 + articles.matched_at 标记位。
    """
    subs = await _enabled_subscriptions(session)
    if not subs:
        return 0

    hits = [
        s.user_id
        for s in subs
        if match_article(
            title=article.title,
            content=article.content,
            category=article.category,
            topics=s.topics,
            keywords=s.keywords,
        )
    ]
    return await _insert_unread(session, hits, article.id)


async def backfill_feed(
    session: AsyncSession,
    subscription: Subscription,
    *,
    days: int | None = None,
    limit: int | None = None,
) -> int:
    """保存订阅后回填历史匹配，返回回填条数。

    没有这一步，用户第一次进「我的订阅」看到的是空页面，演示效果直接垮掉。
    时间窗口和条数都设上限，避免宽泛订阅在老库上一次回填几千条。

    回填写 is_read=False（订阅产品惯例，RSS/公众号首次订阅也全是未读）。
    取舍：更"诚实"的做法是历史写已读，代价是首次进入未读数为 0、看不到未读态。
    """
    days = settings.subscription_backfill_days if days is None else days
    limit = settings.subscription_backfill_limit if limit is None else limit

    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(Article)
        .where(func.coalesce(Article.publish_time, Article.crawled_at) >= since)
        .order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        )
        .limit(limit)
    )
    articles = list((await session.execute(stmt)).scalars().all())

    hits = [
        a
        for a in articles
        if match_article(
            title=a.title,
            content=a.content,
            category=a.category,
            topics=subscription.topics,
            keywords=subscription.keywords,
        )
    ]

    inserted = 0
    for a in hits:
        inserted += await _insert_unread(session, [subscription.user_id], a.id)

    logger.info(
        f"订阅回填 user={subscription.user_id} 窗口={days}天 "
        f"候选={len(articles)} 命中={len(hits)} 新增未读={inserted}"
    )
    # 单条时批量插入反而更慢，这里命中数通常不大，逐条可读性更好
    return inserted
