import json
import logging
from datetime import date
from typing import TypedDict

import google.generativeai as genai

from app.config import settings
from app.services.rating_prompt import RATING_SYSTEM_PROMPT, ARTICLE_PROMPT_TEMPLATE, BATCH_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# Track daily Gemini API usage (resets each day)
_usage_tracker = {
    "date": None,
    "requests": 0,
}
MAX_DAILY_REQUESTS = 20  # Gemini free tier RPD limit


def _check_rate_limit() -> bool:
    """Check if we're within the daily rate limit."""
    today = date.today()
    if _usage_tracker["date"] != today:
        _usage_tracker["date"] = today
        _usage_tracker["requests"] = 0
    return _usage_tracker["requests"] < MAX_DAILY_REQUESTS


def _increment_usage():
    """Increment the daily usage counter."""
    _usage_tracker["requests"] += 1
    remaining = MAX_DAILY_REQUESTS - _usage_tracker["requests"]
    logger.info(f"Gemini API usage: {_usage_tracker['requests']}/{MAX_DAILY_REQUESTS} today ({remaining} remaining)")


def get_gemini_usage() -> dict:
    """Get current Gemini API usage stats."""
    today = date.today()
    if _usage_tracker["date"] != today:
        return {"requests": 0, "limit": MAX_DAILY_REQUESTS, "remaining": MAX_DAILY_REQUESTS}

    remaining = MAX_DAILY_REQUESTS - _usage_tracker["requests"]
    return {
        "requests": _usage_tracker["requests"],
        "limit": MAX_DAILY_REQUESTS,
        "remaining": remaining,
    }


class RatingResult(TypedDict):
    score: int | None
    excluded_reason: str | None
    rationale: str


class ArticleRater:
    _instance: "ArticleRater | None" = None
    _model: genai.GenerativeModel | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_model(self) -> genai.GenerativeModel:
        """Lazy initialization of the model."""
        if self._model is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not configured")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel("gemini-2.0-flash")
        return self._model

    def can_rate(self) -> bool:
        """Check if we can make another rating request today."""
        return _check_rate_limit()

    def get_remaining_requests(self) -> int:
        """Get number of remaining requests for today."""
        today = date.today()
        if _usage_tracker["date"] != today:
            return MAX_DAILY_REQUESTS
        return MAX_DAILY_REQUESTS - _usage_tracker["requests"]

    async def rate_article(self, title: str, summary: str, source: str) -> RatingResult:
        """Rate a single article."""
        # Check rate limit before making request
        if not _check_rate_limit():
            logger.warning("Gemini API daily limit reached, skipping rating")
            return RatingResult(score=None, excluded_reason=None, rationale="Daily limit reached")

        prompt = ARTICLE_PROMPT_TEMPLATE.format(
            title=title,
            summary=summary or "No summary available",
            source=source,
        )

        try:
            model = self._get_model()
            response = await model.generate_content_async(
                [RATING_SYSTEM_PROMPT, prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json"
                ),
            )
            _increment_usage()
            result = json.loads(response.text)
            return RatingResult(
                score=int(result["score"]) if result.get("score") is not None else None,
                excluded_reason=result.get("excluded_reason"),
                rationale=result.get("rationale", ""),
            )
        except Exception as e:
            logger.error(f"Rating failed for '{title}': {e}")
            return RatingResult(score=None, excluded_reason=None, rationale=f"Error: {e}")

    async def rate_articles_batch(self, articles: list[dict]) -> list[RatingResult]:
        """Rate multiple articles in a single API call.

        Args:
            articles: List of dicts with 'title', 'summary', 'source' keys

        Returns:
            List of RatingResult in same order as input
        """
        if not articles:
            return []

        # Check rate limit before making request
        if not _check_rate_limit():
            logger.warning("Gemini API daily limit reached, skipping batch rating")
            return [RatingResult(score=None, excluded_reason=None, rationale="Daily limit reached") for _ in articles]

        # Format articles for the prompt
        articles_text = "\n\n".join(
            f"Article {i+1}:\nTitle: {a.get('title', '')}\nSummary: {a.get('summary') or 'No summary available'}\nSource: {a.get('source', '')}"
            for i, a in enumerate(articles)
        )
        prompt = BATCH_PROMPT_TEMPLATE.format(articles=articles_text)

        try:
            model = self._get_model()
            response = await model.generate_content_async(
                [RATING_SYSTEM_PROMPT, prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json"
                ),
            )
            _increment_usage()
            results = json.loads(response.text)

            # Ensure we got an array
            if not isinstance(results, list):
                results = [results]

            # Map results to RatingResult objects
            ratings = []
            for i, article in enumerate(articles):
                if i < len(results):
                    r = results[i]
                    ratings.append(RatingResult(
                        score=int(r["score"]) if r.get("score") is not None else None,
                        excluded_reason=r.get("excluded_reason"),
                        rationale=r.get("rationale", ""),
                    ))
                else:
                    # Missing result for this article
                    logger.warning(f"No rating returned for article {i+1}: {article.get('title', '')[:50]}")
                    ratings.append(RatingResult(score=None, excluded_reason=None, rationale="Missing from batch response"))

            logger.info(f"Batch rated {len(articles)} articles in single API call")
            return ratings

        except Exception as e:
            logger.error(f"Batch rating failed: {e}")
            # Return failed results for all articles
            return [RatingResult(score=None, excluded_reason=None, rationale=f"Batch error: {e}") for _ in articles]


# Lazy singleton
def get_rater() -> ArticleRater:
    return ArticleRater()
