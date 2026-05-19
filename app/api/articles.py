"""文章相关 API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Article
from app.schemas.article import (
    ArticleDetail,
    ArticleListItem,
    ArticleListResponse,
    CategoryCount,
    SourceCount,
)

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("", response_model=ArticleListResponse, summary="文章列表")
async def list_articles(
    page: int = Query(1, ge=1, description="页码,从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    category: str | None = Query(None, description="按分类筛选"),
    source: str | None = Query(None, description="按数据源筛选"),
    keyword: str | None = Query(None, description="标题关键词搜索"),
    db: AsyncSession = Depends(get_db),
):
    """
    分页获取文章列表。按发布时间倒序排列。

    - **category**: 学业/活动/党团/就业/其他
    - **source**: wechat_mp / cuc_cs_notice / cuc_jwc_notice
    - **keyword**: 在标题中模糊匹配
    """
    # 构建过滤条件
    stmt = select(Article)
    count_stmt = select(func.count(Article.id))

    if category:
        stmt = stmt.where(Article.category == category)
        count_stmt = count_stmt.where(Article.category == category)
    if source:
        stmt = stmt.where(Article.source == source)
        count_stmt = count_stmt.where(Article.source == source)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(Article.title.ilike(pattern))
        count_stmt = count_stmt.where(Article.title.ilike(pattern))

    # 总数
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页 + 排序
    stmt = (
        stmt.order_by(
            Article.publish_time.desc().nullslast(),
            Article.crawled_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    articles = result.scalars().all()

    return ArticleListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ArticleListItem.model_validate(a) for a in articles],
    )


@router.get(
    "/categories",
    response_model=list[CategoryCount],
    summary="分类聚合(给前端做筛选 tab 用)",
)
async def list_categories(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Article.category, func.count(Article.id).label("count"))
        .group_by(Article.category)
        .order_by(func.count(Article.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [CategoryCount(category=r[0], count=r[1]) for r in rows]


@router.get(
    "/sources",
    response_model=list[SourceCount],
    summary="数据源列表",
)
async def list_sources(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Article.source, func.count(Article.id).label("count"))
        .group_by(Article.source)
        .order_by(func.count(Article.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [SourceCount(source=r[0], count=r[1]) for r in rows]


@router.get(
    "/{article_id}",
    response_model=ArticleDetail,
    summary="文章详情",
)
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    return ArticleDetail.model_validate(article)
