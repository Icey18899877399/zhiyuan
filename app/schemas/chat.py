"""Chat 接口请求/响应 schemas"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    agent: str | None = Field(
        None,
        description="前端当前选中的 agent 类别（学业/活动/党团/就业/其他）；为空则不限分类",
    )
    user_id: int | None = Field(None, description="可选：登录用户 id，用于写 ChatLog")


class RetrievedRef(BaseModel):
    id: int
    title: str
    source: str
    source_url: str
    category: str


class ChatResponse(BaseModel):
    success: bool = True
    answer: str
    intent: str = Field(..., description="本次回答归属的 agent / 意图标签")
    retrieved: list[RetrievedRef] = Field(default_factory=list)
