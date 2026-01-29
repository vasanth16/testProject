from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Article
from app.schemas import ArticleResponse, ArticleListResponse, CategoryCount, RegionCount
from app.services.news_fetcher import fetch_and_store

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
    """Return list of categories with article counts."""
    query = (
        select(Article.category, func.count(Article.id).label("count"))
        .where(Article.category.isnot(None))
        .group_by(Article.category)
        .order_by(func.count(Article.id).desc())
    )
    result = await session.execute(query)
    rows = result.all()

    return [CategoryCount(name=row.category, count=row.count) for row in rows]


@router.get("/regions", response_model=list[RegionCount])
async def get_regions(session: AsyncSession = Depends(get_session)):
    """Return list of regions with article counts."""
    query = (
        select(Article.region, func.count(Article.id).label("count"))
        .where(Article.region.isnot(None))
        .group_by(Article.region)
        .order_by(func.count(Article.id).desc())
    )
    result = await session.execute(query)
    rows = result.all()

    return [RegionCount(name=row.region, count=row.count) for row in rows]


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Return article statistics including today's count."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Count articles published today
    today_count_result = await session.execute(
        select(func.count(Article.id)).where(Article.published_at >= today_start)
    )
    today_count = today_count_result.scalar_one()

    # Total count
    total_result = await session.execute(select(func.count(Article.id)))
    total_count = total_result.scalar_one()

    return {
        "today": today_count,
        "total": total_count,
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
