"""
中传计算机与网络空间安全学院官网通知公告爬虫

⚠️ 这是一个**骨架**。需要先确认学院官网的实际 URL 与 HTML 结构后，
   修改 LIST_URL 和两个 _parse_* 方法的选择器。

如何确认 HTML 结构：
  1. 浏览器打开学院通知列表页
  2. F12 → Elements → 选中一条通知，看它的 DOM 标签 / class 名
  3. 把下方的 CSS selector 改成实际的标签

使用：
  python -m scripts.run_crawler cuc_cs_notice --max 3
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


class CucCsNoticeSpider(BaseSpider):
    """学院官网通知公告"""

    source = "cuc_cs_notice"

    # TODO: 替换为学院官网通知列表页 URL
    LIST_URL = "https://cs.cuc.edu.cn/notices/"

    def __init__(self, max_pages: int = 3, sleep: float = 1.0) -> None:
        super().__init__()
        self.max_pages = max_pages
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    # ---- 解析层（待用户确认 HTML 后调整 selector）----

    def _parse_list_page(
        self, html: str
    ) -> list[tuple[str, str, datetime | None]]:
        """解析列表页 → [(title, detail_url, publish_time), ...]"""
        soup = BeautifulSoup(html, "lxml")
        items: list[tuple[str, str, datetime | None]] = []

        # TODO: 把下面这个 selector 替换为实际的
        # 常见结构示例：
        #   <ul class="notice-list">
        #     <li>
        #       <a href="/notice/123.html">通知标题</a>
        #       <span class="date">2025-04-20</span>
        #     </li>
        #   </ul>
        for li in soup.select("ul.notice-list li"):
            a = li.find("a")
            if not a:
                continue
            title = a.get_text().strip()
            href = a.get("href", "")
            if not title or not href:
                continue
            url = urljoin(self.LIST_URL, href)

            publish_time = None
            date_tag = li.find("span", class_="date")
            if date_tag:
                date_str = date_tag.get_text().strip()
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                    try:
                        publish_time = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue

            items.append((title, url, publish_time))
        return items

    def _parse_detail_page(self, html: str) -> str | None:
        """解析详情页正文"""
        soup = BeautifulSoup(html, "lxml")

        # TODO: 替换为实际的正文容器
        body = (
            soup.find("div", class_="article-content")
            or soup.find("div", class_="content")
            or soup.find("div", id="content")
        )
        if not body:
            return None

        paragraphs: list[str] = []
        for tag in body.find_all(["p", "div", "section"]):
            text = tag.get_text().strip()
            if text and len(text) > 5:  # 过滤过短的 div
                paragraphs.append(text)

        if not paragraphs:
            return None
        return "\n\n".join(paragraphs)

    # ---- 抓取主流程 ----

    async def crawl(self) -> AsyncIterator[ParsedArticle]:
        for page in range(1, self.max_pages + 1):
            list_url = (
                self.LIST_URL
                if page == 1
                else f"{self.LIST_URL}?page={page}"
            )
            try:
                r = self.session.get(list_url, timeout=15)
                r.raise_for_status()
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
