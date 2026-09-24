"""subscriptions

Revision ID: 516eaf7b8938
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19 16:49:10.281055

M5 关键词订阅与更新提醒：新增 subscriptions 表（一个用户一份配置）。

注意本文件由 autogenerate 生成后**手工清理过**，去掉了两处与本次改动无关的内容：

1. `op.drop_index('idx_articles_embedding_cosine')` —— autogenerate 想删掉它，
   因为该索引是 b2c3d4e5f6a7_pgvector_embedding 迁移里手工建的，
   Article 模型的 __table_args__ 里没声明。**保留它**，否则向量检索的
   IVFFLAT 余弦索引会被删掉，M2 的检索性能直接退化。
   根因是模型与迁移对不上，属于既有技术债；要根治应把该索引补进 Article.__table_args__。

2. 5 条 crawl_runs 列注释的 alter_column —— 同样是既有的模型/迁移注释漂移
   （a1b2c3d4e5f6_crawl_runs 建表时没写 comment）。与本模块无关，不混进这个 PR。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '516eaf7b8938'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            'user_id', sa.BigInteger(), nullable=False,
            comment='订阅所属用户；一个用户一份配置',
        ),
        sa.Column(
            'topics', postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]', nullable=False,
            comment='关注话题，取值：学业/活动/党团/就业/其他',
        ),
        sa.Column(
            'keywords', postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]', nullable=False,
            comment='补充关键词，标题或正文子串命中即推送',
        ),
        sa.Column(
            'enabled', sa.Boolean(), server_default='true', nullable=False,
            comment='关闭后不再匹配新通知，历史订阅流保留',
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('subscriptions')
