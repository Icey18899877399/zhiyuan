"""
微信公众号 Spider
基于原 爬虫.py + html_to_txt.py 改造，纳入项目爬虫框架。

关键依赖（在 .env 中配置）:
  - WECHAT_MP_COOKIE: mp.weixin.qq.com 登录态 Cookie
  - WECHAT_MP_TOKEN:  公众号平台 token

使用：
  python -m scripts.run_crawler wechat_mp --max 50
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import requests
from loguru import logger

from app.config import settings
from app.crawler.base import BaseSpider, ParsedArticle
from app.crawler.classifier import classify
from app.crawler.parsers.wechat_html import extract_content, extract_publish_time

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class WechatMpSpider(BaseSpider):
    """微信公众号文章爬虫"""

    source = "wechat_mp"

    def __init__(
        self,
        nickname: str = "中国传媒大学",
        max_articles: int = 50,
        page_size: int = 20,
        sleep_per_article: float = 2.0,
    ) -> None:
        super().__init__()
        self.nickname = nickname
        self.max_articles = max_articles
        self.page_size = page_size
        self.sleep_per_article = sleep_per_article

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Cookie": settings.wechat_mp_cookie,
            }
        )
        self.base_params = {
            "lang": "zh_CN",
            "f": "json",
            "token": settings.wechat_mp_token,
        }

    # ---- 私有方法 ----

    def _get_fakeid(self) -> str | None:
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            **self.base_params,
            "action": "search_biz",
            "query": self.nickname,
            "begin": 0,
            "count": 5,
            "ajax": "1",
        }
        try:
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            lst = data.get("list", [])
            return lst[0]["fakeid"] if lst else None
        except Exception as e:
            logger.error(f"获取 fakeid 失败: {e}")
            return None

    def _get_article_list(
        self, fakeid: str, begin: int, count: int
    ) -> list[dict]:
        url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        params = {
            **self.base_params,
            "query": "",
            "begin": begin,
            "count": count,
            "type": 9,
            "action": "list_ex",
            "fakeid": fakeid,
        }
        try:
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            return data.get("app_msg_list", [])
        except Exception as e:
            logger.error(f"获取文章列表失败 begin={begin}: {e}")
            return []

    def _fetch_article_html(self, url: str) -> str | None:
        try:
            r = self.session.get(
                url, headers={"User-Agent": UA}, timeout=15
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.warning(f"抓取文章失败 {url}: {e}")
            return None

    # ---- 公开接口 ----

    async def crawl(self) -> AsyncIterator[ParsedArticle]:
        if not settings.wechat_mp_cookie or not settings.wechat_mp_token:
            logger.error("WECHAT_MP_COOKIE / WECHAT_MP_TOKEN 未配置，spider 跳过")
            return

        fakeid = self._get_fakeid()
        if not fakeid:
            logger.error(f"无法获取 {self.nickname} 的 fakeid（cookie 可能过期）")
            return
        logger.info(f"目标公众号 {self.nickname} fakeid={fakeid}")

        crawled = 0
        begin = 0

        while crawled < self.max_articles:
            articles = self._get_article_list(fakeid, begin, self.page_size)
            if not articles:
                logger.info(f"列表为空，停止 begin={begin}")
                break

            for art in articles:
                if crawled >= self.max_articles:
                    break

                title = (art.get("title") or "").strip()
                link = (art.get("link") or "").strip()
                if not title or not link:
                    continue

                html = self._fetch_article_html(link)
                if not html:
                    continue

                content = extract_content(html)
                if not content:
                    logger.warning(f"无法解析正文: {title[:30]}")
                    continue

                publish_time = extract_publish_time(html)
                category = classify(title, content)

                yield ParsedArticle(
                    source=self.source,
                    source_url=link,
                    title=title,
                    content=content,
                    category=category,
                    publish_time=publish_time,
                )

                crawled += 1
                await asyncio.sleep(self.sleep_per_article)

            begin += len(articles)

        logger.info(f"{self.source} 本轮共爬取 {crawled} 篇")
