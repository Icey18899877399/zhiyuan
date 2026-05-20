"""数据库导出 / 导入助手

用法：
  # 导出（你这边跑）
  python -m scripts.db_sync dump
  # → 生成 dumps/zhiyuan_20260520_093015.sql
  # 然后把这个文件发给同学

  # 导入（同学拿到 SQL 文件后跑）
  python -m scripts.db_sync restore dumps/zhiyuan_20260520_093015.sql

设计目标：
  - 不用记 pg_dump 一长串参数；docker exec 的细节也封装好
  - 输出文件统一在 dumps/，文件名带时间戳，方便归档
  - 导入用 --no-owner --clean --if-exists，无需对方有同名 PG 用户、
    会自动清理旧表避免主键冲突
  - 跨平台（Windows cmd / macOS / Linux）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 与 docker-compose.yml 保持一致；改了那边要同步改这里
CONTAINER_NAME = "zhiyuan-postgres"
DB_USER = "zhiyuan"
DB_NAME = "zhiyuan"
DUMPS_DIR = Path("dumps")


def _check_container_running() -> bool:
    """确保容器在跑，否则后面 docker exec 一定失败"""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return CONTAINER_NAME in result.stdout


def cmd_dump(args: argparse.Namespace) -> int:
    if not _check_container_running():
        print(
            f"❌ 容器 {CONTAINER_NAME} 没在跑。请先 `docker compose up -d`，"
            "等到 healthy 后再试。",
            file=sys.stderr,
        )
        return 1

    DUMPS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = DUMPS_DIR / f"zhiyuan_{stamp}.sql"

    # pg_dump 关键参数：
    # --no-owner：不绑定原用户名，别人导入不会因为缺 zhiyuan 用户报错
    # --clean --if-exists：导入前自动 drop 旧表，避免主键冲突
    # --column-inserts：用 INSERT INTO ... VALUES 而不是 COPY，跨版本兼容好
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "pg_dump", "-U", DB_USER, "-d", DB_NAME,
        "--no-owner", "--clean", "--if-exists",
    ]
    print(f"→ 正在导出到 {out_file} ...")
    with out_file.open("wb") as f:
        result = subprocess.run(cmd, stdout=f)
    if result.returncode != 0:
        print(f"❌ pg_dump 失败，返回码 {result.returncode}", file=sys.stderr)
        return result.returncode

    size_mb = out_file.stat().st_size / 1024 / 1024
    print(f"✅ 导出完成：{out_file}  ({size_mb:.2f} MB)")
    print(f"   把这个文件发给同学，他用 `python -m scripts.db_sync restore {out_file}` 导入即可")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    in_file = Path(args.file)
    if not in_file.exists():
        print(f"❌ 文件不存在：{in_file}", file=sys.stderr)
        return 1
    if not _check_container_running():
        print(
            f"❌ 容器 {CONTAINER_NAME} 没在跑。请先 `docker compose up -d` "
            "并 `alembic upgrade head` 之后再导入。",
            file=sys.stderr,
        )
        return 1

    size_mb = in_file.stat().st_size / 1024 / 1024
    print(f"→ 正在导入 {in_file} ({size_mb:.2f} MB) ...")

    # docker exec -i 把 stdin 转给容器内进程；psql 从 stdin 读 SQL
    cmd = [
        "docker", "exec", "-i", CONTAINER_NAME,
        "psql", "-U", DB_USER, "-d", DB_NAME, "--quiet",
    ]
    with in_file.open("rb") as f:
        result = subprocess.run(cmd, stdin=f)
    if result.returncode != 0:
        print(f"❌ psql 失败，返回码 {result.returncode}", file=sys.stderr)
        return result.returncode

    # 对账：报一下导入后总条目数
    count_cmd = [
        "docker", "exec", CONTAINER_NAME,
        "psql", "-U", DB_USER, "-d", DB_NAME, "-t", "-A",
        "-c", "SELECT COUNT(*) FROM articles;",
    ]
    count_result = subprocess.run(count_cmd, capture_output=True, text=True)
    article_count = count_result.stdout.strip() if count_result.returncode == 0 else "?"

    print(f"✅ 导入完成。articles 表当前共 {article_count} 条")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="智源数据库导出/导入助手（依赖 docker compose 起的 zhiyuan-postgres）"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("dump", help="导出当前数据库到 dumps/ 下")

    p_restore = sub.add_parser("restore", help="把一份 .sql 文件导入到当前数据库")
    p_restore.add_argument("file", help=".sql 文件路径")

    args = parser.parse_args()
    if args.action == "dump":
        return cmd_dump(args)
    if args.action == "restore":
        return cmd_restore(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
