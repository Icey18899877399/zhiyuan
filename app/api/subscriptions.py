"""订阅接口 - 话题/关键词配置与订阅流

数据流：
    爬虫入库新通知 → fanout_new_article 匹配 → 写 user_unread（未读）
    用户保存订阅   → backfill_feed 回填历史匹配 → 写 user_unread
    本模块只负责读/写配置、读订阅流、标记已读。

身份：前端 localStorage 的设备 ID 经 POST /api/users/ensure 落库成
users.openid，本模块端点用 user_id 路径参数。将来接公众号时把设备 ID
换成真 openid 即可，本模块不用动。

未读状态复用 init 迁移就建好的 user_unread 表，与推送渠道解耦：它只记录
「谁该看到哪篇文章、看没看过」。将来公众号模板消息只要读同一张表、
加一个 pushed_at 列，匹配逻辑一行都不用改。

路由顺序注意：/topics 必须注册在 /{user_id} 之前，否则 "topics" 会被
当成 user_id 去解析。articles.py 里 /categories 先于 /{article_id} 同理。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Article, Subscription, User, UserUnread
from app.schemas.subscription import (
    FeedItem,
    FeedResponse,
    MarkReadRequest,
    MarkReadResponse,
    SubscriptionConfig,
    SubscriptionDetail,
    SubscriptionSaved,
    SubscriptionUpdate,
    TopicCount,
)
from app.services.retrieval import _snippet
from app.services.subscription import (
    CATEGORIES,
    backfill_feed,
    matched_keywords,
    normalize_keywords,
)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


# ───────────────────────────── helpers ─────────────────────────────


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在，请先建档")
    return user


async def _get_subscription(db: AsyncSession, user_id: int) -> Subscription | None:
    stmt = select(Subscription).where(Subscription.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _unread_total(db: AsyncSession, user_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(UserUnread)
        .where(UserUnread.user_id == user_id, UserUnread.is_read.is_(False))
    )
    return int((await db.execute(stmt)).scalar_one())


# ───────────────────────────── 话题 ─────────────────────────────


@router.get("/topics", response_model=list[TopicCount], summary="可选话题列表")
async def list_topics(db: AsyncSession = Depends(get_db)) -> list[TopicCount]:
    """固定返回 5 个话题，附带各话题下已有的通知条数，供前端做选择提示。"""
    stmt = select(Article.category, func.count(Article.id)).group_by(Article.category)
    counts = {r[0]: int(r[1]) for r in (await db.execute(stmt)).all()}
    return [TopicCount(topic=c, count=counts.get(c, 0)) for c in CATEGORIES]


# ───────────────────────────── 订阅配置 ─────────────────────────────


@router.get(
    "/{user_id}",
    response_model=SubscriptionDetail,
    summary="读取订阅配置与未读数",
)
async def get_subscription(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> SubscriptionDetail:
    await _get_user_or_404(db, user_id)
    sub = await _get_subscription(db, user_id)
    return SubscriptionDetail(
        user_id=user_id,
        config=SubscriptionConfig.model_validate(sub) if sub else None,
        unread_total=await _unread_total(db, user_id),
    )


@router.put(
    "/{user_id}",
    response_model=SubscriptionSaved,
    summary="保存订阅（话题 + 关键词），并回填历史匹配",
)
async def save_subscription(
    user_id: int,
    req: SubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
) -> SubscriptionSaved:
    """保存后立刻回填历史匹配。

    没有回填这一步，用户第一次进「我的订阅」看到的是空页面。
    关键词在这里做清洗（去空白、丢过短/过泛词、去重、截断），
    清掉哪些前端不知道，所以响应里返回的是清洗后的结果。
    """
    await _get_user_or_404(db, user_id)

    topics = req.topics
    keywords = normalize_keywords(req.keywords)

    sub = await _get_subscription(db, user_id)
    if sub is None:
        sub = Subscription(user_id=user_id, topics=topics, keywords=keywords)
        db.add(sub)
    else:
        sub.topics = topics
        sub.keywords = keywords
    await db.flush()

    backfilled = await backfill_feed(db, sub)
    unread = await _unread_total(db, user_id)
    await db.commit()

    # 显式 refresh 不能省：更新已有订阅时 updated_at 由 onupdate=func.now() 在
    # 服务端生成，而 UPDATE 不像 INSERT 那样会 RETURNING 回读，SQLAlchemy 就把
    # 该属性标记为待加载。下面构造响应时读它会触发一次隐式 IO，在 async 上下文
    # 里直接抛 MissingGreenlet（表现为 500）。
    await db.refresh(sub)

    return SubscriptionSaved(
        config=SubscriptionConfig.model_validate(sub),
        backfilled=backfilled,
        unread_total=unread,
    )


# ───────────────────────────── 订阅流 ─────────────────────────────


@router.get(
    "/{user_id}/feed",
    response_model=FeedResponse,
    summary="订阅流（匹配到的通知）",
)
async def get_feed(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    unread_only: bool = Query(False, description="只看未读"),
    db: AsyncSession = Depends(get_db),
) -> FeedResponse:
    await _get_user_or_404(db, user_id)
    size = page_size or settings.subscription_feed_page_size

    sub = await _get_subscription(db, user_id)
    keywords = list(sub.keywords) if sub else []

    where = [UserUnread.user_id == user_id]
    if unread_only:
        where.append(UserUnread.is_read.is_(False))

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(UserUnread).where(*where)
            )
        ).scalar_one()
    )

    # 未读排前面（PG 里 false < true），同组内按发布时间倒序，与 articles.py 一致
    stmt = (
        select(UserUnread, Article)
        .join(Article, Article.id == UserUnread.article_id)
        .where(*where)
        .order_by(
            UserUnread.is_read.asc(),
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await db.execute(stmt)).all()

    items = []
    for unread, article in rows:
        hits = matched_keywords(
            title=article.title, content=article.content, keywords=keywords
        )
        items.append(
            FeedItem(
                article_id=article.id,
                title=article.title,
                category=article.category,
                source=article.source,
                source_url=article.source_url,
                publish_time=article.publish_time,
                crawled_at=article.crawled_at,
                is_read=unread.is_read,
                hit_keywords=hits,
                # 命中关键词时摘要定位到命中处；纯话题命中则取正文开头
                snippet=_snippet(article.content, hits),
            )
        )

    return FeedResponse(
        total=total,
        page=page,
        page_size=size,
        unread_total=await _unread_total(db, user_id),
        items=items,
    )


# ───────────────────────────── 标记已读 ─────────────────────────────


@router.post(
    "/{user_id}/read",
    response_model=MarkReadResponse,
    summary="标记已读（指定文章或全部）",
)
async def mark_read(
    user_id: int,
    req: MarkReadRequest,
    db: AsyncSession = Depends(get_db),
) -> MarkReadResponse:
    await _get_user_or_404(db, user_id)

    if not req.all and not req.article_ids:
        raise HTTPException(
            status_code=400, detail="article_ids 为空，且 all 不为 true，没有可标记的内容"
        )

    stmt = update(UserUnread).where(
        UserUnread.user_id == user_id, UserUnread.is_read.is_(False)
    )
    if not req.all:
        stmt = stmt.where(UserUnread.article_id.in_(req.article_ids))

    result = await db.execute(stmt.values(is_read=True))
    updated = int(result.rowcount or 0)
    unread = await _unread_total(db, user_id)
    await db.commit()

    return MarkReadResponse(updated=updated, unread_total=unread)
