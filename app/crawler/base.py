"""
爬虫基类
所有 Spider 继承 BaseSpider，实现 crawl() 方法即可。
基类负责：去重、入库、统计、异常吞咽。
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Article


class ParsedArticle:
    """爬虫产出的中间结构，待入库"""

    __slots__ = (
        "source",
        "source_url",
        "title",
        "content",
        "category",
        "publish_time",
        "content_hash",
    )

    def __init__(
        self,
        source: str,
        source_url: str,
        title: str,
        content: str,
        category: str,
        publish_time: datetime | None,
    ):
        self.source = source
        self.source_url = source_url
        self.title = title
        self.content = content
        self.category = category
        self.publish_time = publish_time
        self.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()


class BaseSpider(ABC):
    """所有爬虫的抽象基类"""

    source: ClassVar[str] = ""  # 子类必须设置

    def __init__(self) -> None:
        if not self.source:
            raise ValueError(
                f"{self.__class__.__name__} 必须设置 class 属性 `source`"
            )

    # ---- 子类要实现的部分 ----

    @abstractmethod
    def crawl(self) -> AsyncIterator[ParsedArticle]:
        """子类实现：异步迭代器，逐篇产出 ParsedArticle"""
        ...

    # ---- 通用执行流程 ----

    async def run(self) -> dict:
        """执行爬虫并入库，返回统计"""
        stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}
        async with AsyncSessionLocal() as session:
            async for parsed in self.crawl():
                stats["total"] += 1
                try:
                    saved = await self._save_one(session, parsed)
                    if saved:
                        stats["inserted"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.exception(f"保存失败 {parsed.source_url}: {e}")
                    stats["errors"] += 1
                    await session.rollback()

                # 每 5 条提交一次，避免长事务 + 崩溃丢失
                if stats["total"] % 5 == 0:
                    await session.commit()
            await session.commit()
        logger.info(f"[{self.source}] 爬取完成 {stats}")
        return stats

    async def _save_one(
        self, session: AsyncSession, parsed: ParsedArticle
    ) -> bool:
        """单条入库；URL 或 hash 命中重复返回 False"""
        # URL 去重
        existing = await session.execute(
            select(Article.id).where(Article.source_url == parsed.source_url)
        )
        if existing.scalar_one_or_none() is not None:
            return False

        # content_hash 去重（防止不同 URL 推送同一篇）
        existing = await session.execute(
            select(Article.id).where(Article.content_hash == parsed.content_hash)
        )
        if existing.scalar_one_or_none() is not None:
            return False

        article = Article(
            source=parsed.source,
            source_url=parsed.source_url,
            title=parsed.title[:512],  # 防长标题溢出
            content=parsed.content,
            category=parsed.category,
            publish_time=parsed.publish_time,
            content_hash=parsed.content_hash,
        )
        session.add(article)
        await session.flush()
        return True
