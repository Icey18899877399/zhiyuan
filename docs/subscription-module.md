# 关键词订阅与更新提醒

> 对应路线图 **M5「用户画像精准检索 + 关键词订阅主动推送」** 的订阅部分。
> 负责人：智能体公众号组｜2026 年秋季学期

## 这个模块解决什么

平台在 M1/M2 之后已经能自动爬取通知、做向量检索问答，但用户仍然只能**主动**去翻知识库或提问。本模块补上被动的一环：用户声明自己关注的**话题**与**关键词**，平台在爬虫抓到新通知时自动匹配，沉淀到「我的订阅」页，带未读状态。

## 匹配规则

一篇文章命中某个用户的订阅，当且仅当满足**任一**条件：

| 维度 | 规则 | 作用 |
|---|---|---|
| 话题 | `article.category ∈ subscription.topics` | 粗筛，精确匹配五类话题之一 |
| 关键词 | 关键词出现在标题或正文中（不区分大小写） | 精筛，子串匹配 |

- **为什么是「或」而不是「且」**：计划书里关键词是「**补充**」——用户的意思是「我关注就业类通知，另外特别留意『选调生』」。用「且」的话，选了话题又填关键词就几乎什么都匹配不到。
- **话题与关键词都为空**视为「还没设置订阅」，不匹配任何文章，而不是推送全部。
- **关键词用直接子串匹配，不用检索模块的 bi-gram 分词**。`retrieval._tokenize` 是为长句检索设计的，会把「四六级」拆出「六级」，让《英语六级考试报名》这类通知误命中。用户填的是完整词，直接子串更准也更可预期。这条行为由 `tests/test_subscription_matching.py::test_keyword_not_split_into_bigrams` 锁定。
- **关键词清洗**（`normalize_keywords`）：折叠空白、丢弃长度 < 2 的词、丢弃泛词黑名单里的词（「通知」「公告」「学院」等，这些词单独出现会淹没整个订阅流）、去重、上限 20 个。泛词黑名单是硬编码在 `app/services/subscription.py` 里的，可按实际数据再调。

## 数据流

```
爬虫抓到新通知
  └─ BaseSpider._save_one / scripts/import_csv
       └─ [SAVEPOINT] fanout_new_article()   ← 匹配全部启用订阅
            └─ 命中 → INSERT user_unread (ON CONFLICT DO NOTHING)

用户保存订阅
  └─ PUT /api/subscriptions/{uid}
       └─ backfill_feed()                    ← 回填近 N 天历史匹配
            └─ 命中 → INSERT user_unread

用户查看
  └─ GET /api/subscriptions/{uid}/feed       ← 读 user_unread JOIN articles
```

### 两个必须留意的实现点

**1. SAVEPOINT 隔离（`app/crawler/base.py`）**

订阅派发用 `async with session.begin_nested()` 包住。这不是洁癖：asyncpg 里一条语句失败会把整个事务标记为 aborted，紧接着 `run()` 的 `commit()` 会把**刚爬到的文章一起回滚**——提醒功能故障反过来吃掉核心入库。SAVEPOINT 让派发单独回滚，文章照常提交。

已实测：把 `fanout_new_article` 换成必定抛错的桩，`_save_one` 仍返回 `True`、文章仍在库中。

**2. `ON CONFLICT DO NOTHING` 而不是 `DO UPDATE`**

`user_unread` 的复合主键 `(user_id, article_id)` 天然保证幂等。刻意用 `DO NOTHING`：已读的行不能被重新标成未读，否则用户每次改订阅，读过的通知会全部「复活」。

**3. 为什么要回填**

没有回填，用户第一次进「我的订阅」看到的是空页面。保存订阅时对最近 `SUBSCRIPTION_BACKFILL_DAYS`（默认 30）天、最多 `SUBSCRIPTION_BACKFILL_LIMIT`（默认 200）条文章跑一次匹配。回填写 `is_read = False`（订阅产品惯例，RSS / 公众号首次订阅也全是未读）。

## 身份方案

前端 `localStorage` 生成一个 UUID 当 `openid`，调 `POST /api/users/ensure` 建档，之后所有接口用返回的 `user_id`。

选择匿名设备 ID 而不是微信登录的原因：不依赖备案域名和公网回调，本地就能跑通、能演示；而 `users.openid` 这个字段本身就是为公众号预留的。

**公众号预留点**（计划书要求「为后续公众号端联动预留入口」）：

1. `users.openid` 是关键承载。将来公众号 OAuth 拿到真实 openid 后，把前端传的设备 ID 换成真 openid 即可，`users` 表和订阅模块都不用改。
2. `user_unread` 表与推送渠道解耦——它只记录「谁该看到哪篇文章、看没看过」。将来公众号模板消息只要读同一张表、加一个 `pushed_at` 列，匹配逻辑一行都不用动。
3. `match_new_article` / `fanout_new_article` 是独立的服务函数，公众号侧的定时推送可以直接复用。

**本模块不做实际推送**，只做网页端未读提醒。

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/users/ensure` | 按 openid 幂等建档，返回 `user_id` |
| GET | `/api/subscriptions/topics` | 可选话题列表 + 各类通知数 |
| GET | `/api/subscriptions/{user_id}` | 读订阅配置与未读总数 |
| PUT | `/api/subscriptions/{user_id}` | 保存话题 + 关键词，自动回填历史 |
| GET | `/api/subscriptions/{user_id}/feed` | 订阅流，支持 `page` / `page_size` / `unread_only` |
| POST | `/api/subscriptions/{user_id}/read` | 标记已读，body 支持 `{"article_ids":[...]}` 或 `{"all": true}` |

启动服务后可在 `/docs` 上直接试。

## 演示步骤

```bash
cp .env.example .env          # EMBEDDING_PROVIDER=disabled 时无需任何 API Key
docker compose up -d          # 等 zhiyuan-postgres 显示 healthy
alembic upgrade head
python scripts/import_csv.py --csv articles.csv --limit 20   # 灌一批通知
uvicorn app.main:app --reload --port 8000
```

浏览器打开 `http://localhost:8000/subscribe.html`：

1. 页面自动建档 → 选「学业」「就业」两个话题，加关键词「奖学金」「选调生」
2. 点保存 → 立刻看到回填出来的历史匹配（验证回填生效）
3. 点某条「标记已读」→ 未读数减少，刷新后仍是已读（验证落库而非前端状态）
4. 切到「每日数据」页 → 侧边栏「我的订阅」旁有未读徽标（验证跨页提醒）
5. 切深色模式 → 样式正常

## 已知限制

| 限制 | 说明 |
|---|---|
| 换设备/清缓存 = 丢订阅 | 匿名设备 ID 方案的固有语义。页面展示「本机身份码」并可复制，属可自助恢复；接公众号 openid 后自然消失 |
| 同一浏览器多人共用 | 同上，共享一个 openid。页面文案写明是「本机订阅」 |
| `user_unread` 无 TTL | 随时间线性增长。当前量级无影响；将来可加「清理 90 天前已读记录」的维护任务 |
| 匹配是 O(文章数 × 订阅数) | 每次入库拉全部启用订阅到内存匹配。演示量级（订阅 < 100）无感；订阅数上万时应改为入库只写 article、匹配交给独立调度任务 |
| 实时匹配只在入库时触发 | 没有独立的「补匹配」任务，历史文章靠保存订阅时的回填覆盖 |
| `users.subscribed_tags` 仍然闲置 | 那是身份设置页的画像标签，与本模块的订阅配置是两回事。将来 M5 后半段「用户画像精准检索」可以把两者打通 |

## 测试

```bash
pytest tests/test_subscription_matching.py -v
```

覆盖 `normalize_keywords` / `matched_keywords` / `match_article` 三个纯函数，不依赖数据库。

DB 路径（`fanout_new_article` / `backfill_feed` / 全部端点）没有 pytest 覆盖——本仓库 `tests/` 下没有 `conftest.py` 也没有测试库，这是既有约定。这部分靠演示页和 `/docs` 手工验证。
