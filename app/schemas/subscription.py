"""订阅与用户建档接口的请求/响应 schemas"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.subscription import CATEGORIES

# ───────────────────────── 用户建档 ─────────────────────────


class UserEnsureRequest(BaseModel):
    openid: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="匿名设备 ID（前端 localStorage 生成的 UUID）",
    )
    nickname: str | None = Field(None, max_length=64)


class UserEnsureResponse(BaseModel):
    user_id: int
    openid: str
    created: bool = Field(..., description="本次调用是否新建了用户")


# ───────────────────────── 话题 ─────────────────────────


class TopicCount(BaseModel):
    topic: str
    count: int = Field(..., description="该话题下已有的通知条数")


# ───────────────────────── 订阅配置 ─────────────────────────


class SubscriptionUpdate(BaseModel):
    """保存订阅的请求体。

    话题必须是 CATEGORIES 里的值（从 services 层 import，单一真相源），
    填了别的一律 422，比静默丢弃更容易发现问题。
    """

    topics: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("topics")
    @classmethod
    def _validate_topics(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in CATEGORIES]
        if bad:
            raise ValueError(
                f"未知话题：{'、'.join(bad)}；可选：{'、'.join(CATEGORIES)}"
            )
        return list(dict.fromkeys(v))  # 去重保序


class SubscriptionConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topics: list[str]
    keywords: list[str]
    enabled: bool
    updated_at: datetime | None


class SubscriptionDetail(BaseModel):
    """GET /api/subscriptions/{user_id}

    config 为 None 表示该用户还没保存过订阅。
    """

    user_id: int
    config: SubscriptionConfig | None
    unread_total: int


class SubscriptionSaved(BaseModel):
    """PUT /api/subscriptions/{user_id}"""

    config: SubscriptionConfig
    backfilled: int = Field(..., description="保存时回填的历史匹配条数")
    unread_total: int


# ───────────────────────── 订阅流 ─────────────────────────


class FeedItem(BaseModel):
    article_id: int
    title: str
    category: str
    source: str
    source_url: str
    publish_time: datetime | None
    crawled_at: datetime
    is_read: bool
    hit_keywords: list[str] = Field(
        default_factory=list,
        description="命中的关键词，用于前端展示「命中：考研、选课」；话题命中时为空",
    )
    snippet: str = Field("", description="命中的上下文片段；没有关键词命中时取正文开头")


class FeedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    unread_total: int
    items: list[FeedItem]


# ───────────────────────── 标记已读 ─────────────────────────


class MarkReadRequest(BaseModel):
    article_ids: list[int] = Field(default_factory=list, max_length=500)
    all: bool = Field(False, description="true 表示把该用户全部未读标记为已读")


class MarkReadResponse(BaseModel):
    updated: int
    unread_total: int
