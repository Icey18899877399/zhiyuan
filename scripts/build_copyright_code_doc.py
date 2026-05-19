"""按软著要求拼接源代码鉴别材料（前部 + 后部）。

用法：
    python -m scripts.build_copyright_code_doc

输出：
    docs/copyright/智源-代码-前部.md
    docs/copyright/智源-代码-后部.md

规则（与 docs/copyright/代码提取清单.md 一致）：
    - 每页 60 行
    - 页眉含软件全称、版本号、当前页码 / 总页码
    - 文件之间用 ==== 横线 + 文件名 ==== 分隔
    - 代码完全来自仓库真实文件，未经 AI 编造
"""

from __future__ import annotations

from pathlib import Path

SOFTWARE_FULL_NAME = "智源—高校智能信息服务平台"
VERSION = "V1.0"
LINES_PER_PAGE = 60

REPO_ROOT = Path(__file__).resolve().parent.parent

# 前部：后端核心 + 数据模型 + API + 服务层 + 调度器 + 爬虫基础
FRONT_FILES: list[str] = [
    "app/main.py",
    "app/config.py",
    "app/database.py",
    "app/__init__.py",
    "app/models/__init__.py",
    "app/models/article.py",
    "app/models/user.py",
    "app/models/user_unread.py",
    "app/models/chat_log.py",
    "app/schemas/__init__.py",
    "app/schemas/article.py",
    "app/schemas/chat.py",
    "app/api/__init__.py",
    "app/api/articles.py",
    "app/api/chat.py",
    "app/services/__init__.py",
    "app/services/deepseek.py",
    "app/services/retrieval.py",
    "app/scheduler.py",
    "alembic/env.py",
    "app/crawler/__init__.py",
    "app/crawler/base.py",
    "app/crawler/classifier.py",
    "app/crawler/parsers/__init__.py",
    "app/crawler/parsers/wechat_html.py",
    "app/crawler/spiders/__init__.py",
    "app/crawler/spiders/cuc_jwc_notice.py",
    "app/crawler/spiders/cuc_cs_notice.py",
]

# 后部：剩余爬虫 + 脚本 + 前端
BACK_FILES: list[str] = [
    "app/crawler/spiders/cuc_career.py",
    "app/crawler/spiders/wechat_mp.py",
    "scripts/__init__.py",
    "scripts/run_crawler.py",
    "scripts/run_api.py",
    "scripts/test_db.py",
    "frontend/index.html",
    "frontend/chat.js",
    "frontend/common.js",
    "frontend/rag.html",
    "frontend/rag.js",
    "frontend/identity.html",
    "frontend/identity.js",
    "frontend/daily.html",
    "frontend/daily.js",
    "frontend/styles.css",
]


def _read_file_lines(rel_path: str) -> list[str]:
    """读取文件全部行（不含末尾换行）。空文件返回 ['（空文件）']。"""
    abs_path = REPO_ROOT / rel_path
    text = abs_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        return ["（空文件）"]
    return lines


def _build_stream(files: list[str]) -> list[str]:
    """把多个文件拼成一条行流，每个文件前加一行分隔符。"""
    stream: list[str] = []
    for rel_path in files:
        lines = _read_file_lines(rel_path)
        separator = f"==== 文件: {rel_path}  ({len(lines)} 行) ===="
        stream.append(separator)
        stream.extend(lines)
    return stream


def _paginate(stream: list[str], part_label: str) -> str:
    """按每页 60 行分页，在每页开头插入页眉。"""
    total_lines = len(stream)
    total_pages = (total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    out: list[str] = []
    for page_idx in range(total_pages):
        start = page_idx * LINES_PER_PAGE
        end = min(start + LINES_PER_PAGE, total_lines)
        header = (
            f"[{SOFTWARE_FULL_NAME}  {VERSION}  代码鉴别材料·{part_label}  "
            f"第 {page_idx + 1} 页 / 共 {total_pages} 页]"
        )
        out.append(header)
        out.append("")
        out.append("```")
        out.extend(stream[start:end])
        out.append("```")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> None:
    output_dir = REPO_ROOT / "docs" / "copyright"
    output_dir.mkdir(parents=True, exist_ok=True)

    for files, part_label, filename in (
        (FRONT_FILES, "前部", "智源-代码-前部.md"),
        (BACK_FILES, "后部", "智源-代码-后部.md"),
    ):
        stream = _build_stream(files)
        document = _paginate(stream, part_label)
        out_path = output_dir / filename
        out_path.write_text(document, encoding="utf-8")
        total_lines = len(stream)
        total_pages = (total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE
        print(
            f"已生成 {out_path.relative_to(REPO_ROOT)}："
            f"{total_lines} 行 / {total_pages} 页"
        )


if __name__ == "__main__":
    main()
