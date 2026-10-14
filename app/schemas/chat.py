"""Chat 接口请求/响应 schemas"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AgentCategory = Literal["学业", "活动", "党团", "就业", "其他"]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    route_mode: Literal["auto", "manual"] = Field(
        "manual",
        description="路由模式；manual 保持现有手动 Agent 行为，auto 根据问题识别意图",
    )
    agent: AgentCategory | None = Field(
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
    citations: list[str] = Field(
        default_factory=list,
        description="回答中对应的引用编号；同一来源可能被多个领域专家引用",
    )


class ChatResponse(BaseModel):
    success: bool = True
    answer: str
    answer_mode: Literal["llm", "retrieval_fallback", "no_context"] = Field(
        "llm", description="回答生成方式：大模型回答、本地检索降级或无资料回答"
    )
    intent: str = Field(..., description="本次回答归属的 agent / 意图标签")
    intents: list[str] = Field(default_factory=list, description="识别出的全部意图，支持复合问题")
    route_source: Literal["manual", "rules", "llm"] = Field(
        "manual", description="意图来源：手动选择、关键词规则或大模型识别"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="路由置信度")
    experts: list[str] = Field(default_factory=list, description="本次调用的专家标识")
    warnings: list[str] = Field(
        default_factory=list,
        description="路由、检索、专家调用、引用校验或降级提示",
    )
    retrieved: list[RetrievedRef] = Field(default_factory=list)
