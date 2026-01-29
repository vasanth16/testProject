import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Rate limit: 5 requests per minute = 12 seconds between calls
GEMINI_RATE_LIMIT_DELAY = 12
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select

from app.config import settings
from app.database import async_session
from app.models import Article
from app.services.news_fetcher import fetch_and_store
from app.services.article_rater import get_rater

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


async def retry_failed_ratings() -> None:
    """Retry rating articles that failed on previous attempts."""
    logger.info("Scheduler: Starting retry of failed ratings")

    async with async_session() as session:
        # Get articles that failed rating (limit to 5 to conserve daily quota)
        result = await session.execute(
            select(Article)
            .where(Article.rating_failed == True)
            .limit(5)
        )
        failed_articles = result.scalars().all()

        if not failed_articles:
            logger.info("Scheduler: No failed articles to retry")
            return

        logger.info(f"Scheduler: Retrying {len(failed_articles)} failed articles")

        rater = get_rater()
        success_count = 0

        for i, article in enumerate(failed_articles):
            # Rate limit: wait 12 seconds between calls (RPM=5)
            if i > 0:
                logger.debug(f"Rate limiting: waiting {GEMINI_RATE_LIMIT_DELAY}s before next API call")
                await asyncio.sleep(GEMINI_RATE_LIMIT_DELAY)

            logger.info(f"Retrying article {i + 1}/{len(failed_articles)}: {article.headline[:50]}")
            rating = await rater.rate_article(
                title=article.headline,
                summary=article.summary or "No summary",
                source=article.source_name,
            )

            score = rating.get("score")
            if score is not None:
                article.hopefulness_score = score
                article.excluded_reason = rating.get("excluded_reason")
                article.is_rated = True
                article.rating_failed = False
                success_count += 1
                logger.debug(f"Retry succeeded: {score}")

        await session.commit()
        logger.info(
            f"Scheduler: Retry complete - {success_count}/{len(failed_articles)} succeeded"
        )


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
        trigger=IntervalTrigger(hours=settings.FETCH_INTERVAL_HOURS),
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

    # Add retry job for failed ratings - run every 2 hours
    scheduler.add_job(
        retry_failed_ratings,
        trigger=IntervalTrigger(hours=2),
        id="retry_ratings",
        name="Retry failed article ratings",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: fetching every {settings.FETCH_INTERVAL_HOURS} hours, "
        "retry ratings every 2 hours, cleanup daily"
    )


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown complete")
