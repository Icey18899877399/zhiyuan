"""pgvector + article embedding

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19 09:30:00.000000

M2 动态 RAG：
- 启用 pgvector 扩展
- articles 加 embedding vector(1024) 列
- 加 IVFFLAT 索引（cosine 距离）

注意：IVFFLAT 索引在表行数 <  几千时收益不大，建议先批量回填 embedding 再 REINDEX。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # 1) 开启 pgvector 扩展（pgvector/pgvector:pg16 镜像自带二进制）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2) articles 加 embedding 列，允许空（旧数据通过 backfill_embeddings 补全）
    op.add_column(
        "articles",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )

    # 3) 余弦距离 IVFFLAT 索引（lists=100 适用于 1k~100k 数量级文章）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_embedding_cosine "
        "ON articles USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_articles_embedding_cosine")
    op.drop_column("articles", "embedding")
    # 不 DROP EXTENSION vector，避免影响其他表（如果未来有的话）
