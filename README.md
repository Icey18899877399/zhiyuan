# 智源 — 高校智能信息服务平台

> 中国传媒大学计算机与网络空间安全学院学生作品。把分散在教务处、各学院网站、就业网、学院公众号上的校园通知统一聚合到一个数据库，按学业 / 活动 / 党团 / 就业 / 行政五个话题做检索增强问答。

## 这是个什么

学生原本要在好几个网站之间反复翻找通知，智源做三件事：

1. **聚合**：定时调度的爬虫每 30 分钟自动巡查 3 个数据源，URL + SHA-256 内容哈希双层去重入库
2. **向量化检索**：新通知入库时同步生成 1024 维 embedding 存入 pgvector；问答按 `余弦相似度 × exp(-λ × age_days)` 加权排序，既匹配语义又偏好新内容
3. **可追溯问答**：DeepSeek 生成回答时附带参考来源链接，用户一键跳转学校原文核对

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI 0.115+，单端口同时托管 API 与前端静态 |
| 数据库 | PostgreSQL 16 + pgvector 扩展（向量列 + IVFFLAT 余弦索引） |
| ORM / 迁移 | SQLAlchemy 2.x async + asyncpg + Alembic |
| 调度 | APScheduler IntervalTrigger，30 分钟轮询 |
| LLM | DeepSeek API（问答） |
| Embedding | 智谱 BigModel `embedding-3` / OpenAI 兼容 / disabled 三档可切，无 key 自动降级到关键词检索 |
| 爬虫 | requests + BeautifulSoup4 + lxml |
| 前端 | 原生 HTML / JS / CSS，4 个页面（对话 / 知识库 / 身份 / 每日数据） |

## 快速启动

### 0. 前置工具

- Python 3.11+
- Docker Desktop
- Git

### 1. 克隆 + 装依赖

```bash
git clone https://github.com/Icey18899877399/zhiyuan.git
cd zhiyuan
pip install -e .
```

### 2. 配置

```bash
cp .env.example .env
# 用编辑器打开 .env，至少填 DEEPSEEK_API_KEY
# 如果要用向量检索，再填 EMBEDDING_PROVIDER=zhipu + ZHIPU_API_KEY
```

### 3. 起数据库

```bash
docker compose up -d
docker compose ps   # 等到 zhiyuan-postgres 显示 (healthy)
```

### 4. 建表 + 启用 pgvector

```bash
alembic upgrade head
```

预期看到 3 行 `INFO  [alembic.runtime.migration] Running upgrade ...`，最后一条会在 PG 里跑 `CREATE EXTENSION vector`。

### 5. 启服务

```bash
uvicorn app.main:app --reload
```

浏览器打开 http://localhost:8000 进入对话页。

### 6.（可选）灌种子数据

仓库里 `articles.csv` 是几百条真实校园通知，跑这条立刻入库：

```bash
python -m scripts.import_csv --csv articles.csv --limit 100
```

跑过之后还可以补 embedding（需要 EMBEDDING_PROVIDER 已配）：

```bash
python -m scripts.backfill_embeddings --batch 32
```

## 项目结构

```
zhiyuan/
├── app/
│   ├── main.py                # FastAPI 入口 + lifespan 拉起调度器 + 单端口托管前端
│   ├── config.py              # pydantic-settings：env 集中配置
│   ├── database.py            # 异步引擎 + 会话工厂
│   ├── scheduler.py           # APScheduler：30 分钟一次三个 spider
│   ├── models/                # ORM 模型
│   │   ├── article.py         #   含 pgvector embedding 列
│   │   ├── crawl_run.py       #   每次跑批一条流水
│   │   ├── chat_log.py        #   问答日志
│   │   ├── user.py
│   │   └── user_unread.py
│   ├── schemas/               # Pydantic 请求/响应模型
│   ├── api/
│   │   ├── articles.py        # GET /api/articles + categories + sources + 详情
│   │   ├── chat.py            # POST /api/chat（RAG 主入口）
│   │   └── stats.py           # GET /api/stats/daily + crawl-runs
│   ├── services/
│   │   ├── deepseek.py        # DeepSeek 异步客户端
│   │   ├── embedding.py       # 多 provider embedding（智谱 / OpenAI / disabled）
│   │   └── retrieval.py       # 向量检索 × 时间衰减；关键词 fallback
│   └── crawler/
│       ├── base.py            # BaseSpider：去重 + CrawlRun 流水 + embedding 钩子
│       ├── classifier.py      # 五话题关键词规则
│       ├── parsers/
│       │   └── wechat_html.py
│       └── spiders/
│           ├── cuc_jwc_notice.py    # 教务处通知
│           ├── cuc_cs_notice.py     # 计网学院通知
│           ├── cuc_career.py        # 就业网通知
│           └── wechat_mp.py         # 学院公众号（需要 cookie + token）
├── alembic/                   # 3 个迁移：init schema → crawl_runs → pgvector + embedding
├── frontend/                  # 4 个页面 + 共享 styles.css
├── scripts/
│   ├── run_crawler.py         # 手动触发任一 spider
│   ├── run_api.py             # uvicorn 启动包装
│   ├── backfill_embeddings.py # 对历史数据幂等回填向量
│   ├── import_csv.py          # 从 articles.csv 灌种子数据
│   └── test_db.py             # 数据库连通烟雾测试
├── tests/                     # pytest 24 例（向量打分 / embedding 降级 / 日界）
├── docs/
│   └── copyright/             # 软著申请材料（业务理解 / 操作手册 / 申请表 / 60 页代码鉴别）
├── articles.csv               # 校园通知种子数据
├── docker-compose.yml         # pgvector/pgvector:pg16
├── pyproject.toml             # 依赖 + ruff + pytest 配置
└── .env.example
```

## 多人协作：数据库同步

每个开发者本地都是各自的 Docker PG 容器，**数据不会自动共享**。需要让所有人看到一致的数据时（演示、对账、测试），用 `scripts/db_sync.py` 走"导出 → 微信发文件 → 导入"流程：

```bash
# 你这边导出（数据多的那台机器）
python -m scripts.db_sync dump
# → 输出 dumps/zhiyuan_20260520_093015.sql，发给同学

# 同学拿到文件后导入（先确保他本地 docker compose up -d 起来了）
python -m scripts.db_sync restore dumps/zhiyuan_20260520_093015.sql
```

`dumps/` 已在 `.gitignore`，SQL 不会被误提交到仓库；体量一般几百 KB 到几 MB，微信群直接发即可。如果未来想 7×24 共享数据，路线是迁到云主机 / 学校实验室服务器跑同一份 Postgres，所有人 `.env` 指向同一个连接串。

## 常用命令

| 操作 | 命令 |
|---|---|
| 启动数据库 | `docker compose up -d` |
| 停止数据库 | `docker compose down` |
| 进 psql | `docker exec -it zhiyuan-postgres psql -U zhiyuan -d zhiyuan` |
| 跑迁移 | `alembic upgrade head` |
| 回滚一步 | `alembic downgrade -1` |
| 启服务 | `uvicorn app.main:app --reload` |
| 手动爬一次 | `python -m scripts.run_crawler cuc_jwc_notice --max 5` |
| 回填 embedding | `python -m scripts.backfill_embeddings --batch 32` |
| 导出数据库 | `python -m scripts.db_sync dump` |
| 导入数据库 | `python -m scripts.db_sync restore dumps/<file>.sql` |
| 跑测试 | `pytest tests/` |
| 静态检查 | `ruff check app scripts tests` |

## 核心 API（浏览器 Try it out 入口：`/docs`）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat` | 智能问答（按 agent 标签做向量检索 + LLM 回答） |
| GET | `/api/articles` | 文章列表，支持 `category` / `source` / `keyword` 筛选 |
| GET | `/api/articles/categories` | 分类聚合（前端做筛选 tab） |
| GET | `/api/articles/{id}` | 单篇文章详情 |
| GET | `/api/stats/daily?date=YYYY-MM-DD` | 当日爬虫巡查 + 新增 + 问答统计 |
| GET | `/api/stats/crawl-runs?limit=20` | 最近 N 次跑批流水 |
| GET | `/api/health` | 健康检查 |

## 关键设计点

### 动态 RAG 检索打分公式

```
score = cosine_similarity(query_emb, article_emb) * exp(-lambda * age_days)
```

- `cosine_similarity`：pgvector 的 `1 - (embedding <=> query)`
- `age_days`：当前时间到 `publish_time`（缺失退回 `crawled_at`）的天数
- `lambda` 默认 0.05，半衰期约 14 天；环境变量 `TIME_DECAY_LAMBDA` 可调

实现见 `app/services/retrieval.py` 的 `_search_by_vector()` 与暴露给测试的 `time_decay_score()`。

### Embedding 不可用时的降级

`app/services/embedding.py` 抽象 `EmbeddingClient`，默认提供智谱 + OpenAI 两个 provider。任何一种情况下都会静默退化到 disabled 状态：
- `EMBEDDING_PROVIDER=disabled`（默认）
- 选了 provider 但对应 API Key 缺失
- 真实调用抛错（网络 / 配额）

降级后 `retrieval.search_articles()` 自动走 `_search_by_keyword()`（中文 bi-gram + ILIKE），对调用方完全透明。

### 增量入库

`app/crawler/base.py` 的 `_save_one()` 用 `articles.source_url`（UNIQUE 约束）+ `articles.content_hash`（SHA-256，UNIQUE 约束）双层去重。同一篇文章被不同 spider 重复抓到也只入库一次。

每次跑批由 `BaseSpider.run()` 开/收一条 `crawl_runs` 流水，前端"每日数据"页直接读这张表。

## 开发约定

- 分支：`main` 受保护，所有改动走 PR 合入
- Commit 信息中英文都行，但要说"做了什么、为什么"
- 改 ORM 模型必须同步生成 `alembic revision --autogenerate -m "msg"` 并跑通本地迁移
- 提交前跑一遍 `pytest && ruff check`

## 路线图

- [x] **M0** 基础架构（FastAPI / pg / 三个爬虫 / 前端 4 页 / DeepSeek 对接）
- [x] **M1** 动态爬取：APScheduler 30 分钟一次 + crawl_runs 流水 + daily 真数据
- [x] **M2** 动态 RAG：pgvector + embedding × 时间衰减 + 降级机制
- [ ] **M3** 多智能体路由（LLM 意图分类 + 复合意图并行 + 6 个领域 prompt）
- [ ] **M4** 微信公众号载体 + 5 秒异步响应架构
- [ ] **M5** 用户画像精准检索 + 关键词订阅主动推送

## 软著申请

`docs/copyright/` 下有完整的 V1.0 软著申报材料草稿：

- `业务理解.md` — 项目业务口径
- `操作手册.md` — 9 章操作手册（含截图占位）
- `代码提取清单.md` — 60 页代码鉴别材料的选材规则
- `申请表信息.md` — 中国版权保护中心线上填报字段表
- `智源-代码-前部.md` / `智源-代码-后部.md` — 实测拼装的 60 页源代码鉴别材料

代码鉴别材料由 `scripts/build_copyright_code_doc.py` 从仓库真实文件读取后拼装，保证审核员可复现。

## 著作权

中国传媒大学。开发者：梁信、刘嘉乐。
