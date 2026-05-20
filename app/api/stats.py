"""运营统计接口

GET /api/stats/daily?date=YYYY-MM-DD
    返回某日的：
    - 各 spider 跑批次数 / 成功数 / 失败数 / 累计新增条目数
    - 当日总新增文章数（按 source / category 维度拆分）
    - 当日 chat 调用总数

GET /api/stats/crawl-runs?limit=20
    最近 N 次跑批流水，用于前端"知识库更新日志"展示
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Article, ChatLog, CrawlRun

router = APIRouter(prefix="/api/stats", tags=["stats"])

# 北京时区固定 +8；与 APScheduler / Postgres TZ 保持一致
_TZ = timezone(timedelta(hours=8))


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """返回 [当日 00:00, 次日 00:00) 的 UTC-aware datetime"""
    start = datetime.combine(d, time.min, tzinfo=_TZ)
    end = start + timedelta(days=1)
    return start, end


@router.get("/daily", summary="按日聚合的爬取与问答统计")
async def daily_stats(
    date_str: str | None = Query(None, alias="date", description="日期 YYYY-MM-DD，默认今日"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if date_str:
        d = date.fromisoformat(date_str)
    else:
        d = datetime.now(_TZ).date()
    start, end = _day_bounds(d)

    # 1) 各 spider 今日跑批统计
    spider_stmt = (
        select(
            CrawlRun.source,
            func.count(CrawlRun.id).label("runs"),
            func.sum(
                case((CrawlRun.status == "success", 1), else_=0)
            ).label("success"),
            func.sum(
                case((CrawlRun.status == "failed", 1), else_=0)
            ).label("failed"),
            func.coalesce(func.sum(CrawlRun.inserted), 0).label("inserted"),
            func.coalesce(func.sum(CrawlRun.total), 0).label("total"),
        )
        .where(CrawlRun.started_at >= start, CrawlRun.started_at < end)
        .group_by(CrawlRun.source)
        .order_by(CrawlRun.source)
    )
    spider_rows = (await db.execute(spider_stmt)).all()
    by_spider = [
        {
            "source": r.source,
            "runs": int(r.runs or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
            "inserted": int(r.inserted or 0),
            "total": int(r.total or 0),
        }
        for r in spider_rows
    ]

    # 2) 今日 articles 新增按 source / category 拆分
    source_stmt = (
        select(Article.source, func.count(Article.id))
        .where(Article.crawled_at >= start, Article.crawled_at < end)
        .group_by(Article.source)
    )
    new_by_source = {
        r[0]: int(r[1]) for r in (await db.execute(source_stmt)).all()
    }

    category_stmt = (
        select(Article.category, func.count(Article.id))
        .where(Article.crawled_at >= start, Article.crawled_at < end)
        .group_by(Article.category)
    )
    new_by_category = {
        r[0]: int(r[1]) for r in (await db.execute(category_stmt)).all()
    }

    # 3) 今日 chat 调用次数
    chat_stmt = select(func.count(ChatLog.id)).where(
        ChatLog.created_at >= start, ChatLog.created_at < end
    )
    chat_count = int((await db.execute(chat_stmt)).scalar() or 0)

    return {
        "date": d.isoformat(),
        "by_spider": by_spider,
        "new_articles": {
            "by_source": new_by_source,
            "by_category": new_by_category,
            "total": sum(new_by_source.values()),
        },
        "chat_count": chat_count,
    }


@router.get("/crawl-runs", summary="最近 N 次爬虫跑批流水")
async def recent_crawl_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(CrawlRun)
        .order_by(CrawlRun.started_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "total": r.total,
            "inserted": r.inserted,
            "skipped": r.skipped,
            "errors": r.errors,
            "error_message": r.error_message,
        }
        for r in rows
    ]
