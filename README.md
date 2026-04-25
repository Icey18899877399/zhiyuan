# 智源 后端（zhiyuan-backend）

中国传媒大学计算机与网络空间安全学院智能信息服务平台后端。

## 技术栈

- Python 3.11 + FastAPI + SQLAlchemy 2.x (async) + asyncpg
- PostgreSQL 16（结构化数据） + Chroma（向量库，Day 2 接入）
- APScheduler（定时任务）
- DeepSeek API（LLM）

## Day 1：本地开发环境搭建

### 0. 前置工具

- Python 3.11+
- Docker Desktop（启动 Postgres 用）
- Git
- 推荐安装 [uv](https://docs.astral.sh/uv/)：`pip install uv`（比 pip/poetry 快 10-100 倍）

### 1. 克隆与依赖安装

```bash
git clone <你的 repo 地址> zhiyuan-backend
cd zhiyuan-backend

# 用 uv 创建虚拟环境并安装依赖（推荐）
uv venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

uv pip install -e ".[dev]"
# 同步驱动（仅 Alembic 用）
uv pip install psycopg2-binary
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 然后用编辑器打开 .env，至少确保 DATABASE_URL 与 docker-compose.yml 中的密码一致
# Day 1 其他字段可以留空
```

### 3. 启动 PostgreSQL

```bash
docker compose up -d
docker compose ps   # 应该看到 postgres healthy
```

### 4. 创建并执行第一次迁移

```bash
# 自动从 SQLAlchemy 模型生成迁移脚本
alembic revision --autogenerate -m "init schema"

# 检查 alembic/versions/ 下生成的文件，确认建表 SQL 符合预期

# 执行迁移
alembic upgrade head
```

### 5. 跑通冒烟测试

```bash
python -m scripts.test_db
```

预期输出：

```
🔌 连接数据库...
✅ 插入成功: <Article id=1 title='Day 1 冒烟测试' source=test>
✅ 查询验证通过: <Article id=1 title='Day 1 冒烟测试' source=test>
🧹 测试数据已清理
🎉 Day 1 数据库链路全部跑通！
```

看到这个输出就 commit & push，**Day 1 完成**。

## 项目结构

```
zhiyuan-backend/
├── app/                    # 主应用包
│   ├── config.py          # pydantic-settings 配置
│   ├── database.py        # 异步引擎 + 会话工厂
│   ├── models/            # SQLAlchemy ORM 模型
│   │   ├── user.py
│   │   ├── article.py
│   │   ├── user_unread.py
│   │   └── chat_log.py
│   └── crawler/           # Day 2 开始：爬虫模块
├── alembic/               # 数据库迁移
├── scripts/               # 一次性脚本（冒烟测试、数据导入等）
├── tests/                 # 单元测试
├── docker-compose.yml     # 本地依赖服务
├── pyproject.toml         # 项目元数据 + 依赖
└── .env.example           # 环境变量示例
```

## 常用命令

| 操作 | 命令 |
|------|------|
| 启动 Postgres | `docker compose up -d` |
| 停止 Postgres | `docker compose down` |
| 进 Postgres CLI | `docker exec -it zhiyuan-postgres psql -U zhiyuan -d zhiyuan` |
| 生成迁移 | `alembic revision --autogenerate -m "msg"` |
| 执行迁移 | `alembic upgrade head` |
| 回滚一步 | `alembic downgrade -1` |
| 查看历史 | `alembic history` |

## 协作规范

- 分支：`main` 保护，所有修改走 `feature/xxx` 分支 + PR
- Commit 信息中文英文都可以，但要写清"做了什么"
- 改动数据库模型必须同步生成迁移并提交
