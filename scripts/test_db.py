"""
Day 1 验收脚本
功能：
  1. 连接数据库
  2. 插入一条假 article
  3. 查出来打印
  4. 清理掉测试数据

运行：python -m scripts.test_db
"""
import asyncio
import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Article


async def main() -> None:
    print("🔌 连接数据库...")

    async with AsyncSessionLocal() as session:
        # 准备一条测试数据
        test_url = "https://test.example.com/zhiyuan-day1-smoke"
        content = "这是 Day 1 数据库连通性测试文章。"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # 1. 先清理之前可能残留的测试数据
        existing = await session.execute(
            select(Article).where(Article.source_url == test_url)
        )
        for old in existing.scalars().all():
            await session.delete(old)
        await session.commit()

        # 2. 插入新数据
        article = Article(
            source="test",
            source_url=test_url,
            title="Day 1 冒烟测试",
            content=content,
            category="其他",
            publish_time=datetime.now(UTC),
            content_hash=content_hash,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)
        print(f"✅ 插入成功: {article}")

        # 3. 查询验证
        result = await session.execute(
            select(Article).where(Article.source_url == test_url)
        )
        found = result.scalar_one()
        assert found.title == "Day 1 冒烟测试"
        assert found.content_hash == content_hash
        print(f"✅ 查询验证通过: {found}")

        # 4. 清理
        await session.delete(found)
        await session.commit()
        print("🧹 测试数据已清理")

    print("\n🎉 Day 1 数据库链路全部跑通！")


if __name__ == "__main__":
    asyncio.run(main())
