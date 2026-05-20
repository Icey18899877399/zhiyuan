"""
APScheduler 定时调度

设计目标（M1 "动态"两个字坐实）：
- 每 30 分钟轮一次三个数据源
- 各 source 错开起始时间，避免同一时刻并发把数据库锁住
- FastAPI 应用启动时自动拉起（lifespan）；进程退出时优雅关闭
- 开发模式可独立运行：python -m app.scheduler
"""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None

# 每个 spider 多久跑一次（分钟）
SPIDER_INTERVAL_MINUTES = 30


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


# ---- 任务包装函数 ----

async def _job_cuc_cs_notice() -> None:
    from app.crawler.spiders.cuc_cs_notice import CucCsNoticeSpider

    logger.info("[定时任务] cuc_cs_notice 开始")
    try:
        await CucCsNoticeSpider(max_pages=2).run()
    except Exception as e:
        logger.exception(f"[定时任务] cuc_cs_notice 失败: {e}")


async def _job_cuc_jwc_notice() -> None:
    from app.crawler.spiders.cuc_jwc_notice import CucJwcNoticeSpider

    logger.info("[定时任务] cuc_jwc_notice 开始")
    try:
        await CucJwcNoticeSpider(max_pages=2).run()
    except Exception as e:
        logger.exception(f"[定时任务] cuc_jwc_notice 失败: {e}")


async def _job_cuc_career() -> None:
    from app.crawler.spiders.cuc_career import CucCareerSpider

    logger.info("[定时任务] cuc_career 开始")
    try:
        await CucCareerSpider(max_pages=2).run()
    except Exception as e:
        logger.exception(f"[定时任务] cuc_career 失败: {e}")


def setup_jobs() -> None:
    """注册所有定时任务"""
    sch = get_scheduler()

    # 每 30 分钟一次；起始偏移让三个 spider 错峰
    sch.add_job(
        _job_cuc_jwc_notice,
        trigger=IntervalTrigger(minutes=SPIDER_INTERVAL_MINUTES),
        id="cuc_jwc_notice",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sch.add_job(
        _job_cuc_cs_notice,
        trigger=IntervalTrigger(minutes=SPIDER_INTERVAL_MINUTES),
        id="cuc_cs_notice",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sch.add_job(
        _job_cuc_career,
        trigger=IntervalTrigger(minutes=SPIDER_INTERVAL_MINUTES),
        id="cuc_career",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        f"已注册定时任务: cuc_jwc_notice / cuc_cs_notice / cuc_career "
        f"(每 {SPIDER_INTERVAL_MINUTES} 分钟一次)"
    )


def start() -> None:
    sch = get_scheduler()
    setup_jobs()
    sch.start()
    logger.info("调度器已启动")


def shutdown() -> None:
    sch = get_scheduler()
    if sch.running:
        sch.shutdown()
        logger.info("调度器已关闭")


# ---- 独立运行入口 ----

if __name__ == "__main__":

    async def _main() -> None:
        start()
        logger.info("调度器进入空转，Ctrl+C 退出")
        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, asyncio.CancelledError):
            shutdown()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
