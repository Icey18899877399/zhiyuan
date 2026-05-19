"""爬虫运行流水 - 每次跑批一条记录，用于演示"动态爬取"节奏"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CrawlRun(Base):
    """一条 CrawlRun = 一次 spider.run() 的完整流水"""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="数据源标识，与 articles.source 一致"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="抓取条目数")
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="新入库数")
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="重复跳过数")
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="失败数")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running",
        comment="running / success / failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="失败时的异常摘要"
    )

    __table_args__ = (
        Index("idx_crawl_runs_started_at", started_at.desc()),
        Index("idx_crawl_runs_source", source),
    )

    def __repr__(self) -> str:
        return (
            f"<CrawlRun id={self.id} source={self.source} status={self.status} "
            f"inserted={self.inserted}>"
        )
