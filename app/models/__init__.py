"""
模型集合
注意：所有 ORM 模型必须在此处导入，
否则 Alembic autogenerate 会找不到表。
"""
from app.models.article import Article  # noqa: F401
from app.models.chat_log import ChatLog  # noqa: F401
from app.models.crawl_run import CrawlRun  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_unread import UserUnread  # noqa: F401
