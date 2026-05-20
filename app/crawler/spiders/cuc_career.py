"""
中国传媒大学就业信息网爬虫
站点: https://jy.cuc.edu.cn/
栏目: 招聘信息 / 实习信息 / 选调生 / 国际组织

适配 BaseSpider 的 async generator 接口：crawl() 逐篇 yield ParsedArticle，
入库 / 去重 / CrawlRun 流水统计统一在 BaseSpider.run() 里完成。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from app.crawler.base import BaseSpider, ParsedArticle
from app.crawler.classifier import classify

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}

# 各栏目入口；学校 CMS 翻页模式 list.htm / list2.htm / list3.htm
CHANNELS = {
    "招聘信息": "https://jy.cuc.edu.cn/zpxx/list.htm",
    "实习信息": "https://jy.cuc.edu.cn/sxxx/list.htm",
    "选调生":   "https://jy.cuc.edu.cn/xds/list.htm",
}


class CucCareerSpider(BaseSpider):
    """就业信息网爬虫"""

    source = "cuc_career"

    def __init__(self, max_pages: int = 3, sleep: float = 1.0) -> None:
        super().__init__()
        self.max_pages = max_pages
        self.sleep = sleep

    # ---- 列表页 ----

    def _fetch_list(self, channel_url: str, page: int) -> str | None:
        url = channel_url if page == 1 else channel_url.replace(
            "list.htm", f"list{page}.htm"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
            return r.text
        except Exception as e:
            logger.warning(f"抓取列表页失败 {url}: {e}")
            return None

    def _parse_list(self, html: str, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items: list[dict] = []
        for li in soup.select("ul.news_list li, ul.list li, div.list_main li"):
            a = li.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = urljoin(base_url, a["href"])
            date_span = li.find("span")
            date_text = date_span.get_text(strip=True) if date_span else ""
            if title and href.startswith("http"):
                items.append({"title": title, "url": href, "date_text": date_text})
        return items

    # ---- 详情页 ----

    def _fetch_detail(self, url: str) -> str | None:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
            return r.text
        except Exception as e:
            logger.warning(f"抓取详情页失败 {url}: {e}")
            return None

    def _parse_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")

        content_node = (
            soup.select_one("div.v_news_content")
            or soup.select_one("div.article_content")
            or soup.select_one("div.content")
            or soup.select_one("#vsb_content")
        )
        content = content_node.get_text("\n", strip=True) if content_node else ""

        time_node = (
            soup.select_one("span.arti_update")
            or soup.select_one("span.pub_time")
            or soup.select_one("div.info span")
        )
        publish_time: datetime | None = None
        if time_node:
            text = time_node.get_text(strip=True)
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    publish_time = datetime.strptime(text[:19], fmt)
                    break
                except ValueError:
                    continue

        return {"content": content, "publish_time": publish_time}

    # ---- 主流程：async generator ----

    async def crawl(self) -> AsyncIterator[ParsedArticle]:
        for channel_name, channel_url in CHANNELS.items():
            logger.info(f"[{self.source}] 开始爬栏目: {channel_name}")
            for page in range(1, self.max_pages + 1):
                html = self._fetch_list(channel_url, page)
                if not html:
                    break
                items = self._parse_list(html, channel_url)
                if not items:
                    logger.info(f"  第 {page} 页无内容，栏目 {channel_name} 结束")
                    break

                for it in items:
                    detail_html = self._fetch_detail(it["url"])
                    if not detail_html:
                        continue
                    detail = self._parse_detail(detail_html)
                    if not detail["content"]:
                        continue

                    yield ParsedArticle(
                        source=self.source,
                        source_url=it["url"],
                        title=it["title"],
                        content=detail["content"],
                        category=classify(it["title"], detail["content"]) or "就业",
                        publish_time=detail["publish_time"],
                    )

                    await asyncio.sleep(self.sleep)  # 礼貌休眠
