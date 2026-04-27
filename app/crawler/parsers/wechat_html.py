"""
微信公众号文章 HTML 解析
从原 html_to_txt.py 提炼出的纯函数，方便复用与测试。
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup


def extract_publish_time(html: str) -> datetime | None:
    """从微信公众号文章 HTML 中提取发布时间"""
    if not html:
        return None

    # 1) createTime 单引号
    m = re.search(r"var\s+createTime\s*=\s*'([^']+)'", html)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            pass

    # 2) createTime 双引号
    m = re.search(r'var\s+createTime\s*=\s*"([^"]+)"', html)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            pass

    # 3) oriCreateTime 时间戳
    m = re.search(r"var\s+oriCreateTime\s*=\s*'(\d+)'", html)
    if m:
        try:
            ts = int(m.group(1))
            return datetime.fromtimestamp(ts)
        except (ValueError, OverflowError):
            pass

    return None


def extract_content(html: str) -> str | None:
    """从微信公众号文章 HTML 提取正文（纯文本）"""
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    article = soup.find("div", id="js_content") or soup.find(
        "div", class_="rich_media_content"
    )
    if not article:
        return None

    paragraphs: list[str] = []
    for tag in article.find_all(["p", "h1", "h2", "h3", "h4", "section"]):
        text = tag.get_text().strip()
        if text:
            paragraphs.append(text)

    if not paragraphs:
        return None
    return "\n\n".join(paragraphs)
