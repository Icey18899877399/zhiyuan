"""
中国传媒大学就业信息网爬虫
站点: https://jy.cuc.edu.cn/
栏目: 招聘信息 / 实习信息 / 选调生 / 国际组织
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import select

from app.crawler.base import BaseSpider
from app.crawler.classifier import classify
from app.database import AsyncSessionLocal
from app.models import Article

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA}

# 各栏目 URL,翻页用 list{N}.htm 模式(N 从 1 开始,1 通常是 list.htm)
# 实际模式以你打开页面后的"下一页"链接为准,常见三种格式都列出来
CHANNELS = {
    "招聘信息": "https://jy.cuc.edu.cn/zpxx/list.htm",
    "实习信息": "https://jy.cuc.edu.cn/sxxx/list.htm",
    "选调生":   "https://jy.cuc.edu.cn/xds/list.htm",
}


class CucCareerSpider(BaseSpider):
    """就业信息网爬虫"""

    name = "cuc_career"
    source = "cuc_career"

    def __init__(self, max_pages: int = 3) -> None:
        super().__init__()
        self.max_pages = max_pages

    # ---------- 列表页 ----------

    def fetch_list(self, channel_url: str, page: int) -> str | None:
        """抓某个栏目的某一页"""
        # 学校 CMS 翻页常见格式: list.htm / list2.htm / list3.htm
        if page == 1:
            url = channel_url
        else:
            url = channel_url.replace("list.htm", f"list{page}.htm")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = r.apparent_encoding  # 自动猜编码,中文站常用 utf-8 或 gbk
            return r.text
        except Exception as e:
            logger.warning(f"抓取列表页失败 {url}: {e}")
            return None

    def parse_list(self, html: str, base_url: str) -> list[dict]:
        """从列表 HTML 提取条目"""
        soup = BeautifulSoup(html, "lxml")
        items = []
        # 学校 CMS 列表通常是 <ul class="news_list"> 或类似
        # 这里用最宽松的选择器: 所有 a 标签里包含 .htm 链接 + 有日期文本的
        for li in soup.select("ul.news_list li, ul.list li, div.list_main li"):
            a = li.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = urljoin(base_url, a["href"])
            # 日期通常在 <span> 里
            date_span = li.find("span")
            date_text = date_span.get_text(strip=True) if date_span else ""
            if title and href.startswith("http"):
                items.append({
                    "title": title,
                    "url": href,
                    "date_text": date_text,
                })
        return items

    # ---------- 详情页 ----------

    def fetch_detail(self, url: str) -> str | None:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
            return r.text
        except Exception as e:
            logger.warning(f"抓取详情页失败 {url}: {e}")
            return None

    def parse_detail(self, html: str) -> dict:
        """从详情页 HTML 提取正文 + 发布时间"""
        soup = BeautifulSoup(html, "lxml")

        # 正文容器(学校 CMS 常见 class)
        content_node = (
            soup.select_one("div.v_news_content")
            or soup.select_one("div.article_content")
            or soup.select_one("div.content")
            or soup.select_one("#vsb_content")
        )
        content = content_node.get_text("\n", strip=True) if content_node else ""

        # 发布时间(常在 .info / .pub_time / .date)
        time_node = (
            soup.select_one("span.arti_update")
            or soup.select_one("span.pub_time")
            or soup.select_one("div.info span")
        )
        publish_time = None
        if time_node:
            text = time_node.get_text(strip=True)
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    publish_time = datetime.strptime(text[:19], fmt)
                    break
                except ValueError:
                    continue

        return {"content": content, "publish_time": publish_time}

    # ---------- 主流程 ----------

    async def crawl(self) -> dict:
        stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

        async with AsyncSessionLocal() as session:
            for channel_name, channel_url in CHANNELS.items():
                logger.info(f"[{self.name}] 开始爬栏目: {channel_name}")
                for page in range(1, self.max_pages + 1):
                    html = self.fetch_list(channel_url, page)
                    if not html:
                        break
                    items = self.parse_list(html, channel_url)
                    if not items:
                        logger.info(f"  第 {page} 页无内容,栏目结束")
                        break

                    for it in items:
                        stats["total"] += 1
                        url = it["url"]

                        # URL 去重
                        exists = await session.execute(
                            select(Article.id).where(Article.source_url == url)
                        )
                        if exists.scalar_one_or_none():
                            stats["skipped"] += 1
                            continue

                        # 抓详情
                        detail_html = self.fetch_detail(url)
                        if not detail_html:
                            stats["errors"] += 1
                            continue
                        detail = self.parse_detail(detail_html)
                        if not detail["content"]:
                            stats["errors"] += 1
                            continue

                        # 内容 hash 去重
                        content_hash = hashlib.sha256(
                            detail["content"].encode("utf-8")
                        ).hexdigest()
                        hash_exists = await session.execute(
                            select(Article.id).where(
                                Article.content_hash == content_hash
                            )
                        )
                        if hash_exists.scalar_one_or_none():
                            stats["skipped"] += 1
                            continue

                        # 入库
                        category = classify(it["title"], detail["content"])
                        article = Article(
                            source=self.source,
                            source_url=url,
                            title=it["title"][:512],
                            content=detail["content"],
                            category=category or channel_name,  # 保底用栏目名
                            publish_time=detail["publish_time"],
                            content_hash=content_hash,
                        )
                        session.add(article)
                        stats["inserted"] += 1
                        logger.info(
                            f"  ✅ [{channel_name}] {it['title'][:40]}"
                        )

                        # 每 10 篇 commit 一次
                        if stats["inserted"] % 10 == 0:
                            await session.commit()

                        await asyncio.sleep(1)  # 礼貌性休眠,别把学校服务器打挂

                await session.commit()

        logger.info(f"[{self.name}] 爬取完成 {stats}")
        return stats
