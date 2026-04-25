"""
Alembic 迁移环境
关键点：
1. 从 .env 读取 DATABASE_URL_SYNC（迁移用同步驱动）
2. 导入 app.models.* 让 autogenerate 能感知到所有表
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 重要：必须在 import app.* 之前加载 .env
from dotenv import load_dotenv

load_dotenv()

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app import models  # noqa: F401, E402  # 触发模型注册

config = context.config

# 注入连接串（来自 .env）
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """生成 SQL 而非直接执行，调试用"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """直接连库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 列类型变化也纳入对比
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
