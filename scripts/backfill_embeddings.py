"""把 articles 表里 embedding IS NULL 的旧数据补全。

用法：
    python -m scripts.backfill_embeddings              # 默认每批 32 条
    python -m scripts.backfill_embeddings --batch 16
    python -m scripts.backfill_embeddings --limit 200  # 只回填前 200 条（演示用）

前置条件：
    - .env 配置好 EMBEDDING_PROVIDER 与对应 API Key
    - alembic upgrade head 已跑过（embedding 列已存在）

幂等：仅处理 embedding IS NULL 的行；中途崩了再跑也不会重复消耗 API。
"""
from __future__ import annotations

import argparse
import asyncio

from loguru import logger
from sqlalchemy import select, update

from app.crawler.base import _build_embed_input
from app.database import AsyncSessionLocal
from app.models import Article
from app.services import embedding as emb


async def _backfill(batch_size: int, limit: int | None) -> None:
    if not emb.is_enabled():
        logger.error(
            "embedding 未启用（EMBEDDING_PROVIDER=disabled 或 API Key 缺失），"
            "无法回填。请先在 .env 配置 EMBEDDING_PROVIDER=zhipu 与 ZHIPU_API_KEY。"
        )
        return

    total_done = 0
    while True:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Article)
                .where(Article.embedding.is_(None))
                .order_by(Article.id)
                .limit(batch_size)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            if not rows:
                logger.info(f"全部回填完成，本次累计 {total_done} 条")
                return

            inputs = [_build_embed_input(r.title, r.content) for r in rows]
            vectors = await emb.embed_texts(inputs)

            ok = 0
            for article, vec in zip(rows, vectors, strict=True):
                if vec is None:
                    continue
                await session.execute(
                    update(Article).where(Article.id == article.id).values(embedding=vec)
                )
                ok += 1
            await session.commit()
            total_done += ok
            logger.info(
                f"批次完成：处理 {len(rows)} 条 / 成功 {ok} 条 / 累计 {total_done} 条"
            )

            if limit is not None and total_done >= limit:
                logger.info(f"达到 --limit {limit}，停止")
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 articles.embedding")
    parser.add_argument("--batch", type=int, default=32, help="每批条数 (默认 32)")
    parser.add_argument("--limit", type=int, default=None, help="最多回填条数")
    args = parser.parse_args()

    asyncio.run(_backfill(batch_size=args.batch, limit=args.limit))


if __name__ == "__main__":
    main()
