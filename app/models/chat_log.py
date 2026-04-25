"""对话日志 - 既用于优化模型，也是软著演示数据"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_article_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), default=list, comment="本次检索命中的文章 ID 列表"
    )
    feedback: Mapped[int | None] = mapped_column(
        SmallInteger, comment="用户反馈：-1 不满意 / 0 中性 / 1 满意"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ChatLog id={self.id} user={self.user_id} q={self.question[:20]!r}>"
