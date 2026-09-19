"""订阅配置模型 - 用户关注的话题与关键词

一个用户一份配置（`user_id` 唯一约束），含义是"我关心这几类通知，
另外特别留意这几个词"。匹配语义见 app/services/subscription.py：
话题命中 **或** 关键词命中即推送。

注意与 `users.subscribed_tags` 的区别：那个字段是身份设置页的自由标签，
属于用户画像；本表才是订阅配置。两者暂不互相写入。
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="订阅所属用户；一个用户一份配置",
    )
    topics: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
        comment="关注话题，取值：学业/活动/党团/就业/其他",
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
        comment="补充关键词，标题或正文子串命中即推送",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="关闭后不再匹配新通知，历史订阅流保留",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription user={self.user_id} topics={self.topics} "
            f"keywords={len(self.keywords or [])}个>"
        )
