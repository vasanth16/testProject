from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Article
from app.schemas import ArticleResponse, ArticleListResponse, CategoryCount, RegionCount
from app.services.news_fetcher import fetch_and_store
from app.services.guardian_fetcher import get_guardian_usage
from app.services.thenewsapi_fetcher import get_thenewsapi_usage
from app.services.article_rater import get_gemini_usage

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ArticleListResponse)
async def get_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    region: str | None = Query(default=None),
    min_score: int = Query(default=None, ge=0, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Fetch paginated articles filtered by rating score."""
    # Use default threshold if not specified
    score_threshold = min_score if min_score is not None else settings.RATING_THRESHOLD

    # Build base query: only rated articles above threshold
    base_query = select(Article).where(
        Article.is_rated == True,
        Article.hopefulness_score >= score_threshold,
    )

    if category:
        base_query = base_query.where(Article.category == category)
    if region:
        base_query = base_query.where(Article.region == region)

    # Get total count with filters
    count_query = select(func.count()).select_from(base_query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar_one()

    # Get articles sorted by score (desc), then published date (desc)
    query = (
        base_query
        .order_by(Article.hopefulness_score.desc(), Article.published_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    articles = result.scalars().all()

    return ArticleListResponse(
        articles=articles,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(articles) < total,
    )


@router.post("/fetch")
async def trigger_fetch(session: AsyncSession = Depends(get_session)):
    """Trigger fetching articles from all RSS sources."""
    result = await fetch_and_store(session)
    return {"status": "ok", "fetched": result["fetched"], "new": result["new"]}


@router.post("/retry-ratings")
async def trigger_retry_ratings():
    """Manually trigger retry of failed article ratings."""
    from app.utils.scheduler import retry_failed_ratings
    await retry_failed_ratings()
    return {"status": "ok"}


@router.get("/categories", response_model=list[CategoryCount])
async def get_categories(session: AsyncSession = Depends(get_session)):
    """Return list of categories with counts of displayed articles only."""
    query = (
        select(Article.category, func.count(Article.id).label("count"))
        .where(
            Article.category.isnot(None),
            Article.is_rated == True,
            Article.hopefulness_score >= settings.RATING_THRESHOLD,
        )
        .group_by(Article.category)
        .order_by(func.count(Article.id).desc())
    )
    result = await session.execute(query)
    rows = result.all()

    return [CategoryCount(name=row.category, count=row.count) for row in rows]


@router.get("/regions", response_model=list[RegionCount])
async def get_regions(session: AsyncSession = Depends(get_session)):
    """Return list of regions with counts of displayed articles only."""
    query = (
        select(Article.region, func.count(Article.id).label("count"))
        .where(
            Article.region.isnot(None),
            Article.is_rated == True,
            Article.hopefulness_score >= settings.RATING_THRESHOLD,
        )
        .group_by(Article.region)
        .order_by(func.count(Article.id).desc())
    )
    result = await session.execute(query)
    rows = result.all()

    return [RegionCount(name=row.region, count=row.count) for row in rows]


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Return comprehensive statistics for monitoring and testing."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Total count
    total_result = await session.execute(select(func.count(Article.id)))
    total_count = total_result.scalar_one()

    # Count by rating status
    rated_result = await session.execute(
        select(func.count(Article.id)).where(Article.is_rated == True)
    )
    rated_count = rated_result.scalar_one()

    pending_result = await session.execute(
        select(func.count(Article.id)).where(Article.rating_failed == True)
    )
    pending_count = pending_result.scalar_one()

    # Count pre-filtered (has excluded_reason starting with "keyword_")
    filtered_result = await session.execute(
        select(func.count(Article.id)).where(Article.excluded_reason.like("keyword_%"))
    )
    prefiltered_count = filtered_result.scalar_one()

    # Count articles above threshold
    above_threshold_result = await session.execute(
        select(func.count(Article.id)).where(
            Article.is_rated == True,
            Article.hopefulness_score >= settings.RATING_THRESHOLD,
        )
    )
    above_threshold_count = above_threshold_result.scalar_one()

    # Count by source
    source_query = (
        select(Article.source_name, func.count(Article.id).label("count"))
        .group_by(Article.source_name)
        .order_by(func.count(Article.id).desc())
    )
    source_result = await session.execute(source_query)
    sources = {row.source_name: row.count for row in source_result.all()}

    # Count fetched today
    today_result = await session.execute(
        select(func.count(Article.id)).where(Article.fetched_at >= today_start)
    )
    today_count = today_result.scalar_one()

    # Score distribution for rated articles
    score_distribution = {}
    for label, low, high in [("0-25", 0, 25), ("25-50", 25, 50), ("50-75", 50, 75), ("75-100", 75, 101)]:
        bucket_result = await session.execute(
            select(func.count(Article.id)).where(
                Article.is_rated == True,
                Article.hopefulness_score >= low,
                Article.hopefulness_score < high,
            )
        )
        score_distribution[label] = bucket_result.scalar_one()

    return {
        "articles": {
            "total": total_count,
            "rated": rated_count,
            "pending_rating": pending_count,
            "prefiltered": prefiltered_count,
            "above_threshold": above_threshold_count,
            "fetched_today": today_count,
        },
        "score_distribution": score_distribution,
        "sources": sources,
        "api_usage": {
            "guardian": get_guardian_usage(),
            "thenewsapi": get_thenewsapi_usage(),
            "gemini": get_gemini_usage(),
        },
        "config": {
            "rating_threshold": settings.RATING_THRESHOLD,
            "guardian_enabled": settings.GUARDIAN_ENABLED,
            "thenewsapi_enabled": settings.THENEWSAPI_ENABLED,
        },
    }


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Fetch a single article by ID."""
    result = await session.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()

    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    return article
