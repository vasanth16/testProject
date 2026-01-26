import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete

from app.config import settings
from app.database import async_session
from app.models import Article
from app.services.news_fetcher import fetch_and_store

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_fetch() -> None:
    """Fetch articles from RSS sources on schedule."""
    logger.info("Scheduler: Starting scheduled fetch")
    async with async_session() as session:
        result = await fetch_and_store(session)
        logger.info(
            f"Scheduler: Fetch complete - fetched {result['fetched']}, new {result['new']}"
        )


async def cleanup_old_articles() -> None:
    """Delete articles older than 7 days."""
    logger.info("Scheduler: Starting cleanup of old articles")
    cutoff_date = datetime.utcnow() - timedelta(days=7)

    async with async_session() as session:
        result = await session.execute(
            delete(Article).where(Article.published_at < cutoff_date)
        )
        await session.commit()
        deleted_count = result.rowcount
        logger.info(f"Scheduler: Cleanup complete - deleted {deleted_count} old articles")


def start_scheduler() -> None:
    """Start the scheduler with configured jobs."""
    # Run initial fetch immediately on startup
    scheduler.add_job(
        scheduled_fetch,
        id="initial_fetch",
        name="Initial fetch on startup",
        replace_existing=True,
    )

    # Add recurring fetch job
    scheduler.add_job(
        scheduled_fetch,
        trigger=IntervalTrigger(minutes=settings.FETCH_INTERVAL_MINUTES),
        id="fetch_articles",
        name="Fetch articles from RSS sources",
        replace_existing=True,
    )

    # Add cleanup job - run daily
    scheduler.add_job(
        cleanup_old_articles,
        trigger=IntervalTrigger(hours=24),
        id="cleanup_articles",
        name="Delete articles older than 7 days",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: fetching every {settings.FETCH_INTERVAL_MINUTES} minutes, cleanup daily"
    )


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown complete")
