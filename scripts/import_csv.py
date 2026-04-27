"""
articles.csv 批量导入脚本
读取 CSV → 抓 HTML → 解析 → 入库

CSV 格式（首行为表头）：
  标题,链接

用法：
  # 先小批量验证（推荐第一次跑）
  python -m scripts.import_csv --csv articles.csv --limit 20

  # 正式批量导入（断点续传：用 --start 指定起始下标）
  python -m scripts.import_csv --csv articles.csv

  # 中断后从第 500 条继续
  python -m scripts.import_csv --csv articles.csv --start 500
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import sys
from pathlib import Path

import requests
from loguru import logger
from sqlalchemy import select

from app.crawler.classifier import classify
from app.crawler.parsers.wechat_html import (
    extract_content,
    extract_publish_time,
)
from app.database import AsyncSessionLocal
from app.models import Article

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}
SOURCE = "wechat_mp"


def read_csv(csv_path: Path) -> list[tuple[str, str]]:
    """读 CSV → [(title, url), ...]，自动跳过表头"""
    items: list[tuple[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row or len(row) < 2:
                continue
            title, url = row[0].strip(), row[1].strip()
            # 跳过表头：第一行如果不是 http 开头，认为是表头
            if i == 0 and not url.startswith("http"):
                continue
            if title and url and url.startswith("http"):
                items.append((title, url))
    return items


async def url_exists(session, url: str) -> bool:
    res = await session.execute(
        select(Article.id).where(Article.source_url == url)
    )
    return res.scalar_one_or_none() is not None


async def hash_exists(session, content_hash: str) -> bool:
    res = await session.execute(
        select(Article.id).where(Article.content_hash == content_hash)
    )
    return res.scalar_one_or_none() is not None


async def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入 CSV 文章入库")
    parser.add_argument("--csv", default="articles.csv", help="CSV 文件路径")
    parser.add_argument(
        "--limit", type=int, default=0, help="最多处理多少条（0=全部）"
    )
    parser.add_argument(
        "--start", type=int, default=0, help="从第几条开始（断点续传）"
    )
    parser.add_argument(
        "--sleep", type=float, default=2.0, help="每篇间隔秒数（防封）"
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"CSV 文件不存在: {csv_path.resolve()}")
        sys.exit(1)

    items = read_csv(csv_path)
    total_in_csv = len(items)
    logger.info(f"CSV 共 {total_in_csv} 条")

    if args.start > 0:
        items = items[args.start :]
        logger.info(f"从第 {args.start} 条开始，剩 {len(items)} 条")
    if args.limit > 0:
        items = items[: args.limit]
        logger.info(f"本次限制处理 {args.limit} 条")

    stats = {
        "total": 0,
        "inserted": 0,
        "skipped_url": 0,
        "skipped_hash": 0,
        "fetch_failed": 0,
        "parse_failed": 0,
    }

    async with AsyncSessionLocal() as session:
        for idx, (title, url) in enumerate(items, 1):
            stats["total"] += 1
            global_idx = args.start + idx
            prefix = f"[{idx}/{len(items)} | #{global_idx}]"

            # 1) URL 去重
            if await url_exists(session, url):
                logger.info(f"{prefix} ⏭ 跳过(URL存在): {title[:30]}")
                stats["skipped_url"] += 1
                continue

            # 2) 抓 HTML
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                r.raise_for_status()
                html = r.text
            except Exception as e:
                logger.warning(f"{prefix} ✗ 抓取失败: {e}")
                stats["fetch_failed"] += 1
                await asyncio.sleep(args.sleep)
                continue

            # 3) 解析
            content = extract_content(html)
            if not content:
                logger.warning(f"{prefix} ✗ 解析失败: {title[:30]}")
                stats["parse_failed"] += 1
                await asyncio.sleep(args.sleep)
                continue

            publish_time = extract_publish_time(html)
            category = classify(title, content)

            # 4) hash 去重（双保险）
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if await hash_exists(session, content_hash):
                logger.info(f"{prefix} ⏭ 跳过(内容重复): {title[:30]}")
                stats["skipped_hash"] += 1
                await asyncio.sleep(args.sleep)
                continue

            # 5) 入库
            article = Article(
                source=SOURCE,
                source_url=url,
                title=title[:512],
                content=content,
                category=category,
                publish_time=publish_time,
                content_hash=content_hash,
            )
            session.add(article)
            stats["inserted"] += 1
            logger.info(f"{prefix} ✅ [{category}] {title[:30]}")

            # 每 10 篇 commit 一次（断电不丢太多）
            if stats["inserted"] % 10 == 0:
                await session.commit()
                logger.info(f"💾 已提交 commit，累计入库 {stats['inserted']} 篇")

            await asyncio.sleep(args.sleep)

        await session.commit()

    logger.success(f"\n📊 全部完成！\n{stats}")


if __name__ == "__main__":
    asyncio.run(main())
