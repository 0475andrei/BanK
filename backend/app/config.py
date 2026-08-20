"""Central app configuration - the SINGLE Settings object for the whole
project ([A]'s banking backend and [B]'s AI layer both read this one).

Values come from the environment / `.env` only - never hard-code secrets or
per-environment values elsewhere (flow.md rule #7). The `.env` that backs
this lives at `backend/.env`; see `backend/.env.example` for every variable
and `.env` is gitignored.
"""

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `backend/` - this file is backend/app/config.py, so two parents up.
# Pinning the path (rather than a bare ".env") means the settings resolve the
# same way whether you run from backend/, from the repo root, or in Docker.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or unusable."""


class Settings(BaseSettings):
    """Central app configuration. Values come from the environment / .env
    only — never hard-code secrets or per-environment values elsewhere."""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # A developer's .env may carry keys we don't model; ignore them rather
        # than refusing to start.
        extra="ignore",
    )

    ENV: str = "development"

    # Supabase REST (PostgREST) - no direct Postgres connection is used.
    # SUPABASE_KEY must be the "service_role"/"secret" key: this backend is
    # trusted server code, never exposed to a browser. Never the anon key.
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # Server-side session cookie (see core/security.py, core/dependencies.py).
    SESSION_COOKIE_NAME: str = "session_token"
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    RATE_LIMIT_PER_MINUTE: int = 120

    # Password reset OTP delivery - a Microsoft Teams "Workflows" incoming
    # webhook URL (Teams channel > Workflows > "Send webhook alerts to a
    # chat"). See app/core/teams.py. None disables delivery: reset codes are
    # still generated/stored, they just never reach the user.
    TEAMS_WEBHOOK_URL: str | None = None

    # ------------------------------------------------------------------
    # AI layer ([B]-owned app/ai). Azure OpenAI / Azure AI Foundry.
    # ------------------------------------------------------------------
    # Which provider app.ai.service builds by default. "mock" keeps the layer
    # offline; anything else means the real Azure provider, which needs the
    # four AZURE_* values below.
    AI_PROVIDER: str = "mock"

    # The canonical names are the AZURE_OPENAI_* ones. The AZURE_AI_* aliases
    # are accepted as a fallback because that is how an Azure AI Foundry
    # resource labels the same values.
    AZURE_OPENAI_ENDPOINT: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_ENDPOINT", "AZURE_AI_ENDPOINT"),
    )
    AZURE_OPENAI_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "AZURE_AI_API_KEY"),
    )
    AZURE_OPENAI_API_VERSION: str = Field(
        # Recent preview version: required for the gpt-5 family + tool calling.
        default="2025-04-01-preview",
        validation_alias=AliasChoices("AZURE_OPENAI_API_VERSION", "AZURE_AI_API_VERSION"),
    )
    AZURE_OPENAI_DEPLOYMENT: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_DEPLOYMENT", "AZURE_AI_CHAT_DEPLOYMENT"),
    )

    @field_validator("AZURE_OPENAI_ENDPOINT")
    @classmethod
    def _normalise_endpoint(cls, value: str | None) -> str | None:
        """Reduce a Foundry inference URL to the resource root.

        The OpenAI SDK's Azure client appends `/openai/deployments/...` itself,
        so it wants `https://<resource>.services.ai.azure.com`, not the
        `.../models` inference path Foundry shows in its portal.
        """
        if value is None:
            return None
        endpoint = value.strip().rstrip("/")
        if not endpoint:
            return None
        for suffix in ("/models", "/openai/v1", "/openai"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)].rstrip("/")
        return endpoint

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in {"prod", "production"}

    def require_azure(self) -> "AzureOpenAIConfig":
        """Return validated Azure config or raise with an actionable message."""
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.AZURE_OPENAI_ENDPOINT),
                ("AZURE_OPENAI_API_KEY", self.AZURE_OPENAI_API_KEY),
                ("AZURE_OPENAI_DEPLOYMENT", self.AZURE_OPENAI_DEPLOYMENT),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Missing Azure configuration: "
                + ", ".join(missing)
                + f". Add them to {_BACKEND_DIR / '.env'} (see .env.example)."
            )
        # Narrowed by the check above.
        assert self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_API_KEY
        assert self.AZURE_OPENAI_DEPLOYMENT
        return AzureOpenAIConfig(
            endpoint=self.AZURE_OPENAI_ENDPOINT,
            api_key=self.AZURE_OPENAI_API_KEY,
            api_version=self.AZURE_OPENAI_API_VERSION,
            deployment=self.AZURE_OPENAI_DEPLOYMENT,
        )


class AzureOpenAIConfig(BaseSettings):
    """The Azure values, proven present. Never logged."""

    model_config = SettingsConfigDict(extra="forbid")

    endpoint: str
    api_key: str
    api_version: str
    deployment: str


settings = Settings()


def get_settings() -> Settings:
    """The process-wide settings singleton.

    Same object as the module-level `settings`; this accessor exists so the
    AI layer can take `Settings | None` and fall back to the shared instance.
    """
    return settings
