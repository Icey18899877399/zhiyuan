# 智源软著起草计划

> 参考 Fokkyp/SoftwareCopyright-Skill 的工作流：
> https://github.com/Fokkyp/SoftwareCopyright-Skill
> 该 skill 本身只能装在 Codex（`~/.codex/skills/`），但其产出物清单与流程通用，
> 这里把流程在本仓库内"白纸化"列出，前后端跑通后逐项填实即可。

---

## 0. 总体产出（最终交付清单）

按官方要求，最终需要交到中国版权保护中心的材料：

| 材料 | 文件名规范 | 来源 |
|---|---|---|
| 申请表（可线上填报） | `申请表信息.txt`（字段集中整理） | 见 §1 |
| 软件操作说明书（≤ 60 页） | `智源_操作手册.docx` | 见 §2 |
| 源代码鉴别材料 | `智源-代码(前30页).docx` + `智源-代码(后30页).docx` | 见 §3 |
| 申请人身份证明 | 身份证 / 单位营业执照复印件 | 你/学校提供 |
| 委托书（若代理申报） | 由代理机构提供 | 不适用（自办） |

---

## 1. 申请表字段（`申请表信息.txt`）

逐项确认后写入：

| 字段 | 拟定值 / 来源 |
|---|---|
| **软件全称** | 中国传媒大学计算机与网络空间安全学院智源校园智能信息服务平台 |
| **软件简称** | 智源 |
| **版本号** | V1.0 |
| **开发完成日期** | 跑通整合 + 完成爬虫 + LLM 接通的当天 |
| **首次发表日期** | 同上（或之后），与"开发完成"相同也可 |
| **著作权人** | 待定（个人 / 学院 / 团队联合）—— 见下方"决策点" |
| **开发者** | 梁信、刘嘉乐 + 同学（peepingspace）—— 与 pyproject.toml `authors` 字段对齐 |
| **权利取得方式** | 原始取得 |
| **权利范围** | 全部权利 |
| **开发硬件环境** | x86_64 PC（≥ 8GB RAM） |
| **开发软件环境** | Windows / macOS / Linux + Python 3.11 + Docker Desktop |
| **运行硬件环境** | x86_64 服务器（≥ 4 核 8GB） |
| **运行软件环境** | Linux + Python 3.11 + PostgreSQL 16 + 现代浏览器（Chrome/Edge/Safari） |
| **编程语言** | Python（后端）、JavaScript / HTML / CSS（前端） |
| **源程序量（行）** | 用 `cloc` 跑一遍取实际值 |
| **软件用途** | 面向高校师生，聚合教务/学院/就业/公众号通知，并通过大模型 + RAG 提供智能问答 |
| **技术特点** | ① 多源校园信息自动爬取 + 自动分类<br>② 基于 PostgreSQL 的关键词检索 + DeepSeek 大模型的 RAG 问答<br>③ Agent 标签化（学业/活动/党团/就业/行政）按口径分流 |
| **功能模块** | 见 §2 操作手册章节 |

### 决策点（需要你确认）

- 著作权人是 **个人**（梁信 / 刘嘉乐 / 同学三人联合）还是 **学院**？
  - 个人：流程简单，无需盖章
  - 学院：流程稍复杂，但写在简历/评奖更有分量
- 软件版本号定 V1.0 还是带日期（V2026.05）？

---

## 2. 操作手册大纲（`智源_操作手册.docx`，30–60 页）

按 SoftwareCopyright-Skill 的规则：**先理解业务**再写手册，避免空泛功能列表。

```
封面     ：软件名称 / 版本号 / 著作权人 / 日期
目录     ：自动生成
第一章 概述
  1.1 软件简介（高校智能信息服务平台）
  1.2 主要功能（聚合 + RAG 问答 + 分类浏览）
  1.3 运行环境
  1.4 名词约定（Agent、知识库、爬虫源、分类）
第二章 安装与部署
  2.1 依赖：Python 3.11、Docker、PostgreSQL 16
  2.2 后端部署步骤（uv venv → pip install -e . → docker compose up → alembic upgrade → uvicorn）
  2.3 前端访问（FastAPI 单端口托管，浏览器打开 http://host:8000）
  2.4 环境变量说明（.env.example 全字段对照）
第三章 对话中心（index.html）
  3.1 进入对话页（截图）
  3.2 切换 Agent 标签（学业 / 活动 / 党团 / 就业 / 行政）（截图）
  3.3 输入问题、查看回答、查看参考来源（截图）
  3.4 切换深色模式（截图）
第四章 知识库（rag.html）
  4.1 浏览分类聚合（截图）
  4.2 点击分类查看文章列表（截图）
  4.3 跳转到原文链接（截图）
第五章 身份设置（identity.html）
  5.1 填写学院/年级/角色/标签（截图）
  5.2 本地缓存说明
第六章 每日数据（daily.html）
  6.1 选择日期（截图）
  6.2 查看各 Agent 请求次数（截图）
第七章 后端管理
  7.1 触发爬虫（python -m scripts.run_crawler）
  7.2 导入历史数据（python -m scripts.import_csv）
  7.3 查看 API 文档（/docs Swagger 截图）
第八章 常见问题
  Q: 后端报 503 / 未配置 DEEPSEEK_API_KEY → 编辑 .env
  Q: 知识库空 → 检查爬虫是否成功跑过
  Q: 跨域错误 → 检查 CORS_ORIGINS 配置
附录 A：API 接口清单（/api/health、/api/articles、/api/chat 各字段表格）
附录 B：版权声明
```

### 截图清单（每章节都要配图，至少 20 张）

- [ ] 首页（对话中心）— 默认 / 切换 agent 后
- [ ] 提问后的回答 + 参考来源展开
- [ ] 深色模式效果
- [ ] 知识库分类网格
- [ ] 点击某分类后的文章列表
- [ ] 身份设置页（填写前 / 保存后提示）
- [ ] 每日数据表格
- [ ] Swagger 文档 `/docs`
- [ ] 后端启动日志（uvicorn 启动 + lifespan 日志）
- [ ] 爬虫运行截图（python -m scripts.run_crawler）
- [ ] 数据库表内容（DBeaver / psql）

---

## 3. 源代码鉴别材料

规则：

- **源码总行数 ≥ 3000 行**：取**前 30 页 + 后 30 页**，每页约 50 行有效代码
- **不足 3000 行**：全部源码
- 不能掺 AI 编造，必须来自仓库真实代码
- 顶端写明软件名称 / 版本号 / 页码
- 注释、空行可保留，但不应大段灌水

### 取材范围（按重要性排序）

**前 30 页推荐含：**
1. `app/main.py`（FastAPI 入口）
2. `app/config.py`
3. `app/database.py`
4. `app/models/article.py` + `chat_log.py` + `user.py`
5. `app/api/articles.py`
6. `app/api/chat.py`
7. `app/schemas/*.py`
8. `app/services/deepseek.py`
9. `app/services/retrieval.py`

**后 30 页推荐含：**
10. `app/crawler/base.py` + `classifier.py`
11. `app/crawler/spiders/cuc_jwc_notice.py`
12. `app/crawler/spiders/cuc_cs_notice.py`
13. `app/crawler/spiders/cuc_career.py`
14. `app/crawler/parsers/wechat_html.py`
15. `app/scheduler.py`
16. `frontend/chat.js`
17. `frontend/rag.js`
18. `frontend/index.html`（关键片段）
19. `frontend/styles.css`（核心样式）

### 行数统计命令

```bash
# 安装 cloc：sudo apt install cloc / brew install cloc
cloc app frontend --exclude-dir=__pycache__,node_modules
```

把"Python + JavaScript + HTML + CSS"总行数填入申请表的"源程序量"字段。

---

## 4. 申报时间线（建议）

| 阶段 | 内容 | 预计耗时 |
|---|---|---|
| T+0 | 前后端整合跑通（本次提交） | 当天 |
| T+1 | 跑一次完整爬虫，确保知识库有 ≥ 100 篇文章 | 半天 |
| T+2 | 测试 5 个 Agent 标签的问答，截图存档 | 半天 |
| T+3 | 用 cloc 统计行数，填申请表 | 1 小时 |
| T+4 | 写操作手册（参考 §2 大纲） | 2 天 |
| T+5 | 截取源代码前/后 30 页，导出 docx | 半天 |
| T+6 | 内部 review 一遍，修订文字 | 半天 |
| T+7 | 中国版权保护中心线上申报 | 1 小时 |
| T+30 ~ T+60 | 等待审核出证 | 官方周期 |

---

## 5. 当前进度（自检清单）

> 每完成一项就打 [x]

### 整合落地
- [x] 前端静态文件迁入 `frontend/`
- [x] FastAPI 单端口托管前端
- [x] `POST /api/chat` 实现并接入 DeepSeek
- [x] `GET /api/articles/categories` 给 rag.html 用
- [x] `.env.example` 列全所有环境变量
- [ ] 本地跑通 `docker compose up -d && uvicorn app.main:app`
- [ ] 浏览器访问 `http://localhost:8000` 能看到对话页
- [ ] 在对话页能拿到 DeepSeek 真实回答 + 参考来源

### 软著资料
- [ ] 决策：著作权人是个人还是学院
- [ ] 决策：版本号
- [ ] 爬虫已抓 ≥ 100 篇文章
- [ ] 20+ 张功能截图
- [ ] `cloc` 行数统计
- [ ] 操作手册 DOCX
- [ ] 代码前 30 页 / 后 30 页 DOCX
- [ ] 申请表字段确认
- [ ] 线上申报提交

---

## 6. 备注

- **不要在仓库里提交 docx / 截图等大文件**，单独建一个 `software-copyright/` 文件夹放本地或放协作文档；本仓库只留这份 plan + 最终公开版的 LICENSE 即可
- 软件名称、版本号、页眉、申请表字段务必**全程一致**，审核员最爱挑这个错
- 中文版权保护中心官网：https://register.ccopyright.com.cn
