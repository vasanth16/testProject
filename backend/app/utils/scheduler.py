import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select

from app.config import settings
from app.database import async_session
from app.models import Article
from app.services.news_fetcher import fetch_and_store, ARTICLES_PER_BATCH
from app.services.article_rater import get_rater
from app.services.keyword_filter import pre_filter_article
from app.services.article_selector import select_balanced_articles

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
    """Delete articles older than 14 days."""
    logger.info("Scheduler: Starting cleanup of old articles")
    cutoff_date = datetime.utcnow() - timedelta(days=14)

    async with async_session() as session:
        result = await session.execute(
            delete(Article).where(Article.published_at < cutoff_date)
        )
        await session.commit()
        deleted_count = result.rowcount
        logger.info(f"Scheduler: Cleanup complete - deleted {deleted_count} old articles")


async def retry_failed_ratings() -> None:
    """Retry rating articles that failed on previous attempts."""
    rater = get_rater()

    # Check if we have any API quota left
    if not rater.can_rate():
        logger.info("Scheduler: Gemini daily limit reached, skipping retry")
        return

    remaining = rater.get_remaining_requests()
    logger.info(f"Scheduler: Starting retry of failed ratings ({remaining} API calls remaining)")

    async with async_session() as session:
        # Get unrated articles
        result = await session.execute(
            select(Article)
            .where(Article.rating_failed == True)
            .order_by(Article.published_at.desc())
            .limit(50)
        )
        pending_articles = result.scalars().all()

        if not pending_articles:
            logger.info("Scheduler: No failed articles to retry")
            return

        logger.info(f"Scheduler: Found {len(pending_articles)} pending articles")

        # Apply pre-filter first
        passed_filter = []
        filtered_count = 0

        for article in pending_articles:
            filter_result = pre_filter_article(
                article.headline,
                article.summary or ""
            )

            if not filter_result["passed"]:
                # Mark as filtered out, skip Gemini
                article.is_rated = True
                article.rating_failed = False
                article.excluded_reason = filter_result["reason"]
                filtered_count += 1
            else:
                passed_filter.append(article)

        if filtered_count > 0:
            logger.info(f"Scheduler: Pre-filtered {filtered_count} articles")

        if not passed_filter:
            await session.commit()
            logger.info("Scheduler: No articles passed pre-filter")
            return

        # Convert to dicts for balanced selection
        article_dicts = [
            {
                "id": a.id,
                "source_name": a.source_name,
                "published": a.published_at,
            }
            for a in passed_filter
        ]

        # Select articles based on remaining API quota (each call rates ARTICLES_PER_BATCH)
        max_to_rate = rater.get_remaining_requests() * ARTICLES_PER_BATCH
        selected_dicts = select_balanced_articles(article_dicts, min(len(passed_filter), max_to_rate))
        selected_ids = {d["id"] for d in selected_dicts}

        # Get the actual article objects for selected items
        articles_to_rate = [a for a in passed_filter if a.id in selected_ids]

        if not articles_to_rate:
            await session.commit()
            return

        sources = set(a.source_name for a in articles_to_rate)
        logger.info(f"Scheduler: Rating up to {len(articles_to_rate)} articles from {len(sources)} sources")

        # Rate articles in batches (multiple articles per API call)
        success_count = 0
        for batch_start in range(0, len(articles_to_rate), ARTICLES_PER_BATCH):
            if not rater.can_rate():
                logger.info(f"Scheduler: Daily limit reached after {success_count} ratings")
                break

            batch = articles_to_rate[batch_start:batch_start + ARTICLES_PER_BATCH]
            batch_input = [
                {"title": a.headline, "summary": a.summary or "No summary", "source": a.source_name}
                for a in batch
            ]

            logger.info(f"Scheduler: Batch rating {len(batch)} articles")
            ratings = await rater.rate_articles_batch(batch_input)

            for article, rating in zip(batch, ratings):
                score = rating.get("score")
                if score is not None:
                    article.hopefulness_score = score
                    article.excluded_reason = rating.get("excluded_reason")
                    article.is_rated = True
                    article.rating_failed = False
                    success_count += 1
                    logger.debug(f"Rated '{article.headline[:30]}': {score}")

            # Delay between batches to respect RPM limit (5 req/min)
            if batch_start + ARTICLES_PER_BATCH < len(articles_to_rate):
                await asyncio.sleep(15)

        await session.commit()
        logger.info(
            f"Scheduler: Retry complete - {success_count} rated, {filtered_count} pre-filtered"
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
        name="Delete articles older than 14 days",
        replace_existing=True,
    )

    # Add retry job for failed ratings - run every hour to use up daily quota
    scheduler.add_job(
        retry_failed_ratings,
        trigger=IntervalTrigger(hours=1),
        id="retry_ratings",
        name="Retry failed article ratings",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: fetching every {settings.FETCH_INTERVAL_HOURS} hours, "
        "retry ratings every hour, cleanup daily"
    )


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown complete")
