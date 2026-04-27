"""
手动触发某个爬虫
用法：
  python -m scripts.run_crawler wechat_mp --max 30
  python -m scripts.run_crawler cuc_cs_notice --max 3
  python -m scripts.run_crawler cuc_jwc_notice --max 3
"""
from __future__ import annotations

import argparse
import asyncio

from loguru import logger


async def main() -> None:
    # 延迟导入以加快帮助信息
    from app.crawler.spiders.cuc_cs_notice import CucCsNoticeSpider
    from app.crawler.spiders.cuc_jwc_notice import CucJwcNoticeSpider
    from app.crawler.spiders.wechat_mp import WechatMpSpider

    spiders = {
        "wechat_mp": WechatMpSpider,
        "cuc_cs_notice": CucCsNoticeSpider,
        "cuc_jwc_notice": CucJwcNoticeSpider,
    }

    parser = argparse.ArgumentParser(description="手动触发爬虫")
    parser.add_argument(
        "spider", choices=spiders.keys(), help="要执行的 spider"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        help="最大数量(wechat_mp 是文章数，cuc_cs_notice / cuc_jwc_notice 是页数)",
    )
    args = parser.parse_args()

    spider_cls = spiders[args.spider]
    if args.spider == "wechat_mp":
        spider = spider_cls(max_articles=args.max)
    else:
        spider = spider_cls(max_pages=args.max)

    stats = await spider.run()
    logger.success(f"完成: {stats}")


if __name__ == "__main__":
    asyncio.run(main())