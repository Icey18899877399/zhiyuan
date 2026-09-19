"""用户接口 - 匿名设备 ID 建档

前端 localStorage 生成一个 UUID 当 openid，首次访问时调本接口建档。
这是计划书里「为后续公众号端联动预留入口」的落点：将来公众号 OAuth
拿到真实 openid 后，把前端传的设备 ID 换成真 openid 即可，
本接口、users 表和订阅模块全都不用改。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.subscription import UserEnsureRequest, UserEnsureResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post(
    "/ensure",
    response_model=UserEnsureResponse,
    summary="按 openid 建档（幂等）",
)
async def ensure_user(
    req: UserEnsureRequest,
    db: AsyncSession = Depends(get_db),
) -> UserEnsureResponse:
    """按 openid 建档，已存在则直接返回。

    前端每次进「我的订阅」页都可以无脑调一次：openid 已有就复用，
    不会重复建档，也不会覆盖已有资料。
    """
    # ON CONFLICT DO NOTHING 而不是先查后插：并发首次调用不会撞唯一索引
    result = await db.execute(
        pg_insert(User)
        .values(openid=req.openid, nickname=req.nickname)
        .on_conflict_do_nothing(index_elements=["openid"])
    )
    created = bool(result.rowcount)
    await db.commit()

    user = (
        await db.execute(select(User).where(User.openid == req.openid))
    ).scalar_one()

    return UserEnsureResponse(user_id=user.id, openid=user.openid, created=created)
