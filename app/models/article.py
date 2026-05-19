"""文章模型 - 校园通知/活动/讲座等聚合内容"""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据源标识")
    source_url: Mapped[str] = mapped_column(
        String(1024), unique=True, nullable=False, comment="原文 URL"
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文纯文本")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="学业/活动/党团/就业/其他"
    )
    publish_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="原文发布时间"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="正文 SHA-256 用于去重"
    )
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # M2 向量列：维度由 settings.embedding_dim 决定（默认 1024）
    # 为空表示该文章尚未生成 embedding（无 key / backfill 未跑到）
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )

    __table_args__ = (
        Index("idx_articles_publish_time", publish_time.desc()),
        Index("idx_articles_category", category),
        Index("idx_articles_source", source),
    )

    def __repr__(self) -> str:
        return f"<Article id={self.id} title={self.title[:30]!r} source={self.source}>"
