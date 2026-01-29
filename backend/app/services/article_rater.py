import json
import logging
from typing import TypedDict

import google.generativeai as genai

from app.config import settings
from app.services.rating_prompt import RATING_SYSTEM_PROMPT, ARTICLE_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


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
            self._model = genai.GenerativeModel("gemini-3-flash-preview")
        return self._model

    async def rate_article(self, title: str, summary: str, source: str) -> RatingResult:
        """Rate a single article."""
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
            result = json.loads(response.text)
            return RatingResult(
                score=int(result["score"]) if result.get("score") is not None else None,
                excluded_reason=result.get("excluded_reason"),
                rationale=result.get("rationale", ""),
            )
        except Exception as e:
            logger.error(f"Rating failed for '{title}': {e}")
            return RatingResult(score=None, excluded_reason=None, rationale=f"Error: {e}")


# Lazy singleton
def get_rater() -> ArticleRater:
    return ArticleRater()
