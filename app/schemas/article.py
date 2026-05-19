"""文章相关 Pydantic schemas"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArticleListItem(BaseModel):
    """列表页的精简版(不含 content,减少传输量)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_url: str
    title: str
    category: str
    publish_time: datetime | None
    crawled_at: datetime


class ArticleDetail(BaseModel):
    """详情页(含完整正文)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_url: str
    title: str
    content: str
    category: str
    publish_time: datetime | None
    crawled_at: datetime


class ArticleListResponse(BaseModel):
    """分页列表响应"""
    total: int
    page: int
    page_size: int
    items: list[ArticleListItem]


class CategoryCount(BaseModel):
    """分类计数"""
    category: str
    count: int


class SourceCount(BaseModel):
    """数据源计数"""
    source: str
    count: int
