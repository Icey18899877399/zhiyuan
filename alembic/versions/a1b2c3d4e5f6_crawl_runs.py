"""crawl_runs

Revision ID: a1b2c3d4e5f6
Revises: bd3a595058f1
Create Date: 2026-05-19 09:00:00.000000

新增 crawl_runs 表，记录每次爬虫跑批的开始/结束时间与统计数。
对应 M1：把"动态"两个字坐实。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "bd3a595058f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            comment="数据源标识，与 articles.source 一致",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="running",
            nullable=False,
            comment="running / success / failed",
        ),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_crawl_runs_started_at",
        "crawl_runs",
        [sa.literal_column("started_at DESC")],
        unique=False,
    )
    op.create_index("idx_crawl_runs_source", "crawl_runs", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_crawl_runs_source", table_name="crawl_runs")
    op.drop_index("idx_crawl_runs_started_at", table_name="crawl_runs")
    op.drop_table("crawl_runs")
