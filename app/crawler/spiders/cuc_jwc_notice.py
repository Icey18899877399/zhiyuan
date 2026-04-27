"""
中传校教务处通知公告爬虫
站点: https://jwc.cuc.edu.cn/6364/list.htm

跟 cuc_cs_notice 用同一套学校 CMS（苏迪 webplus），代码结构一致，
只是栏目从学院通知换成校教务处通知。

使用：
  python -m scripts.run_crawler cuc_jwc_notice --max 3
"""
from __future__ import annotations

import asyncio
import re
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

# 苏迪 webplus CMS 详情页 URL 模式: /YYYY/MMDD/cXXXXaXXXXX/page.htm
DETAIL_URL_PATTERN = re.compile(r"/\d{4}/\d{4}/c\w+/page\.htm$")


class CucJwcNoticeSpider(BaseSpider):
    """中传教务处通知公告"""

    source = "cuc_jwc_notice"

    LIST_URL = "https://jwc.cuc.edu.cn/6364/list.htm"

    def __init__(self, max_pages: int = 3, sleep: float = 1.0) -> None:
        super().__init__()
        self.max_pages = max_pages
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    # ---- 解析层 ----

    def _parse_list_page(
        self, html: str
    ) -> list[tuple[str, str, datetime | None]]:
        """解析列表页 → [(title, detail_url, publish_time), ...]"""
        soup = BeautifulSoup(html, "lxml")
        items: list[tuple[str, str, datetime | None]] = []

        seen_urls: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not DETAIL_URL_PATTERN.search(href):
                continue
            url = urljoin(self.LIST_URL, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a.get_text(separator=" ", strip=True)
            # 清理标题前缀的日期(如 "2026-03-11 通知标题")
            title = re.sub(
                r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s*", "", title
            ).strip()
            if not title or len(title) < 4:
                continue

            # 在父级容器里找日期
            publish_time = None
            parent = a.find_parent(["li", "tr", "div"])
            if parent:
                text = parent.get_text(" ", strip=True)
                m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
                if m:
                    try:
                        publish_time = datetime(
                            int(m.group(1)),
                            int(m.group(2)),
                            int(m.group(3)),
                        )
                    except ValueError:
                        pass

            items.append((title, url, publish_time))
        return items

    def _parse_detail_page(self, html: str) -> str | None:
        """解析详情页正文"""
        soup = BeautifulSoup(html, "lxml")

        body = (
            soup.find("div", class_="wp_articlecontent")
            or soup.find("div", class_="v_news_content")
            or soup.find("div", id="vsb_content")
            or soup.find("div", class_="article-content")
            or soup.find("div", class_="content")
            or soup.find("div", id="content")
        )
        if not body:
            return None

        paragraphs: list[str] = []
        for tag in body.find_all(["p", "div", "section"]):
            text = tag.get_text().strip()
            if text and len(text) > 5:
                paragraphs.append(text)

        if not paragraphs:
            return None
        return "\n\n".join(paragraphs)

    # ---- 抓取主流程 ----

    async def crawl(self) -> AsyncIterator[ParsedArticle]:
        for page in range(1, self.max_pages + 1):
            # 学校 CMS 翻页:list.htm / list2.htm / list3.htm
            if page == 1:
                list_url = self.LIST_URL
            else:
                list_url = self.LIST_URL.replace("list.htm", f"list{page}.htm")

            try:
                r = self.session.get(list_url, timeout=15)
                r.raise_for_status()
                r.encoding = r.apparent_encoding
            except Exception as e:
                logger.warning(f"列表页抓取失败 page={page}: {e}")
                continue

            items = self._parse_list_page(r.text)
            if not items:
                logger.info(f"page={page} 无数据，结束")
                break

            for title, detail_url, publish_time in items:
                try:
                    r = self.session.get(detail_url, timeout=15)
                    r.raise_for_status()
                    r.encoding = r.apparent_encoding
                except Exception as e:
                    logger.warning(f"详情页抓取失败 {detail_url}: {e}")
                    continue

                content = self._parse_detail_page(r.text)
                if not content:
                    continue

                yield ParsedArticle(
                    source=self.source,
                    source_url=detail_url,
                    title=title,
                    content=content,
                    category=classify(title, content),
                    publish_time=publish_time,
                )
                await asyncio.sleep(self.sleep)