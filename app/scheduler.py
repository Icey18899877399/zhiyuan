"""
APScheduler 定时调度
开发模式可独立运行：python -m app.scheduler
后期接到 FastAPI lifespan 里随服务一起启动。
"""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


# ---- 任务包装函数 ----

async def _job_wechat_mp() -> None:
    from app.crawler.spiders.wechat_mp import WechatMpSpider

    logger.info("[定时任务] wechat_mp 开始")
    try:
        await WechatMpSpider(max_articles=20).run()
    except Exception as e:
        logger.exception(f"[定时任务] wechat_mp 失败: {e}")


async def _job_cuc_cs_notice() -> None:
    from app.crawler.spiders.cuc_cs_notice import CucCsNoticeSpider

    logger.info("[定时任务] cuc_cs_notice 开始")
    try:
        await CucCsNoticeSpider(max_pages=2).run()
    except Exception as e:
        logger.exception(f"[定时任务] cuc_cs_notice 失败: {e}")


def setup_jobs() -> None:
    """注册所有定时任务"""
    sch = get_scheduler()

    sch.add_job(
        _job_wechat_mp,
        trigger=CronTrigger(hour="*/6"),  # 每 6 小时
        id="wechat_mp",
        replace_existing=True,
    )
    sch.add_job(
        _job_cuc_cs_notice,
        trigger=CronTrigger(hour="*/3"),  # 每 3 小时
        id="cuc_cs_notice",
        replace_existing=True,
    )

    logger.info("已注册定时任务: wechat_mp(每6h), cuc_cs_notice(每3h)")


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
