"""用户模型"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(64))
    college: Mapped[str | None] = mapped_column(String(64), comment="所属学院")
    grade: Mapped[str | None] = mapped_column(String(16), comment="年级，如 2024")
    role: Mapped[str | None] = mapped_column(String(16), comment="学生/教师")
    subscribed_tags: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} openid={self.openid[:8]}... nickname={self.nickname}>"
