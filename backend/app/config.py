from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app configuration. Values come from the environment / .env
    only — never hard-code secrets or per-environment values elsewhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"

    DATABASE_URL: str = "postgresql+asyncpg://bank:bank@localhost:5432/bank"

    # Server-side session cookie (see core/security.py, core/dependencies.py).
    SESSION_COOKIE_NAME: str = "session_token"
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    RATE_LIMIT_PER_MINUTE: int = 120

    # Consumed by the [B]-owned app/ai module.
    AI_PROVIDER: str = "mock"
    OPENAI_API_KEY: str | None = None

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in {"prod", "production"}


settings = Settings()
