from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False
    FETCH_INTERVAL_HOURS: int = 6
    DATABASE_URL: str = "sqlite+aiosqlite:///./news.db"
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_LEVEL: str = "INFO"
    GEMINI_API_KEY: str = ""
    RATING_THRESHOLD: int = 65

    class Config:
        env_file = ".env"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS as comma-separated list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
