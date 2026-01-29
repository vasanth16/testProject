from datetime import datetime
from pydantic import BaseModel


class ArticleCreate(BaseModel):
    guid: str
    headline: str
    summary: str | None = None
    source_url: str
    source_name: str
    image_url: str | None = None
    published_at: datetime | None = None


class ArticleResponse(BaseModel):
    id: int
    guid: str
    headline: str
    summary: str | None
    source_url: str
    source_name: str
    image_url: str | None
    published_at: datetime | None
    fetched_at: datetime
    category: str | None
    region: str | None
    hopefulness_score: int | None
    is_rated: bool
    rating_failed: bool
    excluded_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ArticleListResponse(BaseModel):
    articles: list[ArticleResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class CategoryCount(BaseModel):
    name: str
    count: int


class RegionCount(BaseModel):
    name: str
    count: int
