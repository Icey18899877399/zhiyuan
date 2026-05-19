"""聊天接口：前端 → 后端 → 知识库检索 → DeepSeek → 写 ChatLog → 返回"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ChatLog
from app.schemas.chat import ChatRequest, ChatResponse, RetrievedRef
from app.services.deepseek import chat_completion
from app.services.retrieval import RetrievedArticle, search_articles

router = APIRouter(prefix="/api", tags=["chat"])

# 前端的 agent.category 字段直接对应 Article.category，校验集合：
VALID_AGENTS = {"学业", "活动", "党团", "就业", "其他"}

SYSTEM_PROMPT = (
    "你是中国传媒大学计算机与网络空间安全学院「智源」校园智能助手。"
    "请只使用下面提供的「参考资料」回答用户问题，做到简洁、准确、有条理。"
    "如果参考资料里没有相关信息，请明确告知用户「目前知识库中没有相关内容」，"
    "不要编造、不要凭空猜测；必要时建议用户去查看原文链接。"
)


def _build_user_prompt(question: str, refs: list[RetrievedArticle]) -> str:
    if not refs:
        return (
            "【参考资料】（暂无相关资料）\n\n"
            f"【用户问题】{question}\n\n"
            "请基于「无相关资料」的事实给出回答。"
        )
    blocks = []
    for i, r in enumerate(refs, 1):
        blocks.append(
            f"[{i}] 标题：{r.title}\n"
            f"    分类：{r.category} | 来源：{r.source}\n"
            f"    摘录：{r.snippet}"
        )
    refs_text = "\n\n".join(blocks)
    return (
        f"【参考资料】\n{refs_text}\n\n"
        f"【用户问题】{question}\n\n"
        "请基于以上参考资料作答，在合适位置可以用 [编号] 引用资料。"
    )


@router.post("/chat", response_model=ChatResponse, summary="智能问答（RAG over 爬虫知识库）")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    if not settings.deepseek_api_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 DEEPSEEK_API_KEY，无法调用大模型。",
        )

    category = req.agent if req.agent in VALID_AGENTS else None
    intent_label = category or "通用助手"

    # 1. 检索
    refs = await search_articles(db, req.question, category=category, top_k=5)
    logger.info(
        f"💬 chat: agent={intent_label} q={req.question!r} hits={len(refs)}"
    )

    # 2. 调 DeepSeek
    user_prompt = _build_user_prompt(req.question, refs)
    try:
        answer = await chat_completion(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("DeepSeek 调用失败")
        raise HTTPException(status_code=502, detail=f"大模型调用失败：{e}") from e

    # 3. 写 ChatLog（用户未登录时 user_id=None 也可以记录）
    try:
        log = ChatLog(
            user_id=req.user_id,
            question=req.question,
            answer=answer,
            retrieved_article_ids=[r.id for r in refs],
        )
        db.add(log)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("ChatLog 写入失败（不影响返回）")

    return ChatResponse(
        success=True,
        answer=answer,
        intent=intent_label,
        retrieved=[
            RetrievedRef(
                id=r.id,
                title=r.title,
                source=r.source,
                source_url=r.source_url,
                category=r.category,
            )
            for r in refs
        ],
    )
