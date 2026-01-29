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

# Rate limit: 5 requests per minute = 12 seconds between calls
GEMINI_RATE_LIMIT_DELAY = 12
# Max articles to rate per fetch cycle (conserve daily quota of 20)
MAX_ARTICLES_PER_FETCH = 5

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


def fetch_all_sources() -> list[dict]:
    """Fetch articles from all RSS sources."""
    all_articles = []

    for source in RSS_SOURCES:
        articles = fetch_rss_feed(source["url"])
        for article in articles:
            article["source_name"] = source["name"]
        all_articles.extend(articles)

    return all_articles


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

    # Rate and store articles one by one (limited to conserve daily quota)
    rater = get_rater()
    new_count = 0
    articles_to_rate = new_articles[:MAX_ARTICLES_PER_FETCH]
    articles_to_store_unrated = new_articles[MAX_ARTICLES_PER_FETCH:]

    if articles_to_store_unrated:
        logger.info(f"Will rate {len(articles_to_rate)} articles now, {len(articles_to_store_unrated)} saved for later")

    for i, article_data in enumerate(articles_to_rate):
        headline = article_data.get("title", "")
        summary = article_data.get("summary") or ""

        # Rate limit: wait 12 seconds between calls (RPM=5)
        if i > 0:
            logger.debug(f"Rate limiting: waiting {GEMINI_RATE_LIMIT_DELAY}s before next API call")
            await asyncio.sleep(GEMINI_RATE_LIMIT_DELAY)

        logger.info(f"Rating article {i + 1}/{len(articles_to_rate)}: {headline[:50]}")
        rating = await rater.rate_article(
            title=headline,
            summary=summary,
            source=article_data.get("source_name", ""),
        )

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

        if score is not None:
            logger.debug(f"Rated '{headline[:50]}': {score} - {rating.get('rationale', '')[:50]}")

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
    """Fetch all RSS sources and store new articles in the database."""
    articles = fetch_all_sources()
    new_count = await store_articles(articles, session)

    return {"fetched": len(articles), "new": new_count}
