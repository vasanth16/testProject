import asyncio
import logging
import re
import feedparser
import httpx
from datetime import datetime
from time import struct_time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article
from app.services.content_filter import detect_category
from app.services.article_rater import get_rater
from app.services.guardian_fetcher import fetch_guardian_articles
from app.services.thenewsapi_fetcher import fetch_thenewsapi_articles
from app.services.keyword_filter import pre_filter_article
from app.services.article_selector import select_balanced_articles

# Batch size for rating (multiple articles per API call)
ARTICLES_PER_BATCH = 10

logger = logging.getLogger(__name__)


RSS_SOURCES = [
    {"name": "Positive News", "url": "https://www.positive.news/feed/"},
    {"name": "Good News Network", "url": "https://www.goodnewsnetwork.org/feed/"},
    {"name": "Reasons to be Cheerful", "url": "https://reasonstobecheerful.world/feed/"},
]


def parse_published_date(date_parsed: struct_time | None) -> datetime | None:
    """Convert feedparser's time tuple to datetime."""
    if date_parsed is None:
        return None
    try:
        return datetime(*date_parsed[:6])
    except (TypeError, ValueError):
        return None


def extract_image_url(entry: dict) -> str | None:
    """Extract image URL from RSS entry using various methods."""
    # Try media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for media in entry.media_content:
            if media.get("medium") == "image" or media.get("type", "").startswith("image/"):
                return media.get("url")
        # If no explicit image type, take first media_content with url
        if entry.media_content[0].get("url"):
            return entry.media_content[0].get("url")

    # Try media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")

    # Try enclosures
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enclosure in entry.enclosures:
            if enclosure.get("type", "").startswith("image/"):
                return enclosure.get("href") or enclosure.get("url")

    # Try links with image type
    if hasattr(entry, "links"):
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href")

    return None


async def fetch_og_image(url: str) -> str | None:
    """Fetch og:image meta tag from article URL."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; BrightWorldNews/1.0)"
            })
            if response.status_code != 200:
                return None

            html = response.text[:50000]  # Only check first 50KB

            # Look for og:image meta tag
            patterns = [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            ]

            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    return match.group(1)

            return None
    except Exception:
        return None


def fetch_rss_feed(url: str) -> list[dict]:
    """Fetch and parse an RSS feed, returning a list of article dicts."""
    try:
        feed = feedparser.parse(url)
        articles = []

        for entry in feed.entries:
            article = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary") or entry.get("description", ""),
                "published": parse_published_date(entry.get("published_parsed")),
                "guid": entry.get("id") or entry.get("link", ""),
                "image_url": extract_image_url(entry),
            }
            articles.append(article)

        return articles
    except Exception:
        return []


def fetch_rss_sources() -> list[dict]:
    """Fetch articles from RSS sources only."""
    all_articles = []

    for source in RSS_SOURCES:
        articles = fetch_rss_feed(source["url"])
        for article in articles:
            article["source_name"] = source["name"]
        all_articles.extend(articles)

    return all_articles


async def fetch_all_sources() -> list[dict]:
    """Fetch articles from all sources (RSS feeds + APIs)."""
    all_articles = []
    source_counts = {}

    # Fetch from RSS feeds (synchronous)
    rss_articles = fetch_rss_sources()
    all_articles.extend(rss_articles)
    source_counts["RSS Feeds"] = len(rss_articles)

    # Fetch from Guardian API
    guardian_articles = await fetch_guardian_articles()
    all_articles.extend(guardian_articles)
    source_counts["The Guardian"] = len(guardian_articles)

    # Fetch from TheNewsAPI
    thenewsapi_articles = await fetch_thenewsapi_articles()
    all_articles.extend(thenewsapi_articles)
    source_counts["TheNewsAPI"] = len(thenewsapi_articles)

    # Deduplicate by guid
    seen_guids = set()
    unique_articles = []
    for article in all_articles:
        guid = article.get("guid")
        if guid and guid not in seen_guids:
            seen_guids.add(guid)
            unique_articles.append(article)

    # Log source breakdown
    for source, count in source_counts.items():
        logger.info(f"  {source}: {count} articles")
    logger.info(f"Total: {len(all_articles)} fetched, {len(unique_articles)} unique after deduplication")

    return unique_articles


async def store_articles(articles: list[dict], session: AsyncSession) -> int:
    """Store articles in the database, rating them with Gemini first."""
    if not articles:
        return 0

    # Get all GUIDs from fetched articles
    guids = [a.get("guid") for a in articles if a.get("guid")]
    if not guids:
        return 0

    # Batch query for existing articles
    result = await session.execute(select(Article.guid).where(Article.guid.in_(guids)))
    existing_guids = set(row[0] for row in result.all())

    # Filter to only new articles
    new_articles = [a for a in articles if a.get("guid") and a["guid"] not in existing_guids]
    if not new_articles:
        logger.info("No new articles to process")
        return 0

    logger.info(f"Processing {len(new_articles)} new articles")

    # Apply keyword pre-filter to save Gemini API calls
    passed_filter = []
    filtered_out = []

    for article_data in new_articles:
        headline = article_data.get("title", "")
        summary = article_data.get("summary") or ""
        filter_result = pre_filter_article(headline, summary)

        if filter_result["passed"]:
            passed_filter.append(article_data)
        else:
            article_data["_filter_reason"] = filter_result["reason"]
            filtered_out.append(article_data)

    if filtered_out:
        logger.info(f"Pre-filter: {len(filtered_out)} articles filtered out, {len(passed_filter)} passed")

    # Use balanced selection (round-robin by source) for fair distribution
    rater = get_rater()
    new_count = 0

    # Calculate how many articles we can rate based on remaining API quota
    # Each API call rates ARTICLES_PER_BATCH articles
    remaining_quota = rater.get_remaining_requests()
    max_to_rate = remaining_quota * ARTICLES_PER_BATCH
    articles_to_rate = select_balanced_articles(passed_filter, max_to_rate) if max_to_rate > 0 else []

    # Get the guids of selected articles to determine which are unrated
    selected_guids = {a.get("guid") for a in articles_to_rate}
    articles_to_store_unrated = [a for a in passed_filter if a.get("guid") not in selected_guids]

    if articles_to_rate:
        sources_selected = set(a.get("source_name") for a in articles_to_rate)
        logger.info(f"Balanced selection: {len(articles_to_rate)} articles from {len(sources_selected)} sources")

    if articles_to_store_unrated:
        logger.info(f"Will rate {len(articles_to_rate)} articles now, {len(articles_to_store_unrated)} saved for later")

    # Store filtered-out articles first (no Gemini call needed)
    for article_data in filtered_out:
        headline = article_data.get("title", "")
        summary = article_data.get("summary") or ""
        category = detect_category(headline, summary)

        image_url = article_data.get("image_url")
        if not image_url:
            article_link = article_data.get("link", "")
            if article_link:
                image_url = await fetch_og_image(article_link)

        article = Article(
            guid=article_data.get("guid"),
            headline=headline,
            summary=summary,
            source_url=article_data.get("link", ""),
            source_name=article_data.get("source_name", ""),
            image_url=image_url,
            published_at=article_data.get("published"),
            hopefulness_score=None,
            category=category,
            is_rated=True,  # Mark as rated so it doesn't go to retry queue
            rating_failed=False,
            excluded_reason=article_data.get("_filter_reason"),
        )
        session.add(article)
        new_count += 1

    # Rate articles in batches (multiple articles per API call)
    rated_count = 0
    for batch_start in range(0, len(articles_to_rate), ARTICLES_PER_BATCH):
        # Check if we still have API quota
        if not rater.can_rate():
            logger.info(f"Gemini daily limit reached after rating {rated_count} articles")
            # Move remaining to unrated list
            articles_to_store_unrated.extend(articles_to_rate[batch_start:])
            break

        batch = articles_to_rate[batch_start:batch_start + ARTICLES_PER_BATCH]
        batch_input = [
            {"title": a.get("title", ""), "summary": a.get("summary") or "", "source": a.get("source_name", "")}
            for a in batch
        ]

        logger.info(f"Batch rating {len(batch)} articles in single API call")
        ratings = await rater.rate_articles_batch(batch_input)

        for article_data, rating in zip(batch, ratings):
            headline = article_data.get("title", "")
            summary = article_data.get("summary") or ""
            guid = article_data.get("guid")

            # Detect category
            category = detect_category(headline, summary)

            # Get image URL
            image_url = article_data.get("image_url")
            if not image_url:
                article_link = article_data.get("link", "")
                if article_link:
                    image_url = await fetch_og_image(article_link)

            # Determine rating status
            score = rating.get("score")
            rating_failed = score is None
            is_rated = not rating_failed

            article = Article(
                guid=guid,
                headline=headline,
                summary=summary,
                source_url=article_data.get("link", ""),
                source_name=article_data.get("source_name", ""),
                image_url=image_url,
                published_at=article_data.get("published"),
                hopefulness_score=score,
                category=category,
                is_rated=is_rated,
                rating_failed=rating_failed,
                excluded_reason=rating.get("excluded_reason"),
            )
            session.add(article)
            new_count += 1
            rated_count += 1

            if score is not None:
                logger.debug(f"Rated '{headline[:50]}': {score}")

        # Delay between batches to respect RPM limit (5 req/min)
        if batch_start + ARTICLES_PER_BATCH < len(articles_to_rate):
            await asyncio.sleep(15)

    if rated_count > 0:
        logger.info(f"Rated {rated_count} articles this fetch cycle")

    # Store remaining articles without rating (will be rated later by retry job)
    for article_data in articles_to_store_unrated:
        headline = article_data.get("title", "")
        summary = article_data.get("summary") or ""
        category = detect_category(headline, summary)

        image_url = article_data.get("image_url")
        if not image_url:
            article_link = article_data.get("link", "")
            if article_link:
                image_url = await fetch_og_image(article_link)

        article = Article(
            guid=article_data.get("guid"),
            headline=headline,
            summary=summary,
            source_url=article_data.get("link", ""),
            source_name=article_data.get("source_name", ""),
            image_url=image_url,
            published_at=article_data.get("published"),
            hopefulness_score=None,
            category=category,
            is_rated=False,
            rating_failed=True,  # Mark as failed so retry job picks them up
            excluded_reason=None,
        )
        session.add(article)
        new_count += 1

    await session.commit()
    rated_count = len(articles_to_rate)
    unrated_count = len(articles_to_store_unrated)
    logger.info(f"Stored {new_count} articles ({rated_count} rated, {unrated_count} pending)")
    return new_count


async def fetch_and_store(session: AsyncSession) -> dict:
    """Fetch from all sources and store new articles in the database."""
    articles = await fetch_all_sources()
    new_count = await store_articles(articles, session)

    return {"fetched": len(articles), "new": new_count}
