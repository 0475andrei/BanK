"""Application settings.

Every value is read from the environment / `.env`. Nothing is hard-coded here
(rule 7 in flow.md: secrets from env only). Person A owns the wider config; this
module currently holds only what the AI layer needs and is meant to be extended
in place rather than replaced.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root — `.env` lives next to pyproject.toml, one level above `app/`.
_REPO_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or unusable."""


class Settings(BaseSettings):
    """Environment-backed settings.

    The canonical variable names are the ``AZURE_OPENAI_*`` ones. The
    ``AZURE_AI_*`` aliases are accepted as a fallback because that is how an
    Azure AI Foundry resource labels the same three values.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # The shared .env carries unrelated keys; ignore anything we don't model.
        extra="ignore",
    )

    azure_openai_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_ENDPOINT", "AZURE_AI_ENDPOINT"),
    )
    azure_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "AZURE_AI_API_KEY"),
    )
    azure_openai_api_version: str = Field(
        # Recent preview version: required for the gpt-5 family + tool calling.
        default="2025-04-01-preview",
        validation_alias=AliasChoices("AZURE_OPENAI_API_VERSION", "AZURE_AI_API_VERSION"),
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AZURE_OPENAI_DEPLOYMENT", "AZURE_AI_CHAT_DEPLOYMENT"
        ),
    )

    @field_validator("azure_openai_endpoint")
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

    def require_azure(self) -> "AzureOpenAIConfig":
        """Return validated Azure config or raise with an actionable message."""
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", self.azure_openai_api_key),
                ("AZURE_OPENAI_DEPLOYMENT", self.azure_openai_deployment),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Missing Azure configuration: "
                + ", ".join(missing)
                + f". Add them to {_REPO_ROOT / '.env'} (see .env.example)."
            )
        # Narrowed by the check above.
        assert self.azure_openai_endpoint and self.azure_openai_api_key
        assert self.azure_openai_deployment
        return AzureOpenAIConfig(
            endpoint=self.azure_openai_endpoint,
            api_key=self.azure_openai_api_key,
            api_version=self.azure_openai_api_version,
            deployment=self.azure_openai_deployment,
        )


class AzureOpenAIConfig(BaseSettings):
    """The Azure values, proven present. Never logged."""

    model_config = SettingsConfigDict(extra="forbid")

    endpoint: str
    api_key: str
    api_version: str
    deployment: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
