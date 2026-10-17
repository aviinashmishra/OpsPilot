"""Application configuration.

All settings are read from environment variables (or a .env file). No secrets
are hard-coded. Defaults are chosen so the platform starts locally with SQLite,
an in-process worker, and a deterministic mock LLM provider - with zero external
services - while production deployments use PostgreSQL, Redis/Celery and real
model providers.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Repo-root .env (written by scripts/start.ps1) first, then backend/.env overrides.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- Application -----------------------------------------------------
    app_name: str = "OpsPilot AI"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    # Comma-separated (as written in .env / env vars). A plain string on purpose: pydantic-settings
    # would otherwise require JSON for list fields and crash on "a,b".
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ----------------------------------------------------------
    database_url: str = Field("sqlite:///./opspilot.db", repr=False)  # may embed a password
    db_echo: bool = False
    db_pool_size: int = 10
    # Recycle pooled connections before serverless Postgres (Neon) suspends idle compute and drops them.
    db_pool_recycle_seconds: int = 300
    # PostgreSQL guard rails: a wait on a row lock longer than this fails (the job retries) instead
    # of hanging a worker forever; idle-in-transaction sessions are killed so they cannot hold locks.
    db_lock_timeout_ms: int = 30_000
    db_idle_in_transaction_timeout_ms: int = 300_000
    enable_pgvector: bool = False

    # --- Queue / workers -----------------------------------------------------
    redis_url: str | None = None
    worker_mode: Literal["inline", "thread", "db", "celery"] = "thread"
    worker_concurrency: int = 4
    workflow_max_steps: int = 50
    workflow_default_timeout_seconds: int = 600
    workflow_heartbeat_stale_seconds: int = 120
    job_lease_seconds: int = 120
    batch_item_stale_seconds: int = 300

    # --- Security ------------------------------------------------------------
    # Secrets are excluded from repr so a logged Settings object (e.g. in a traceback) cannot leak them.
    secret_key: str = Field("dev-only-change-me-0000000000000000000000000000", repr=False)
    encryption_key: str | None = Field(None, repr=False)  # Fernet key for integration credentials
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "opspilot-local"
    jwt_audience: str = "opspilot-api"
    access_token_ttl_minutes: int = 120
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    allow_password_login: bool = True  # local dev issuer; disable when OIDC is configured
    allow_signup: bool = True  # self-serve "Create a workspace" for new companies
    webhook_signing_secret: str | None = Field(None, repr=False)
    # Password for the seeded demo accounts. Unset = the public local-dev default (shown on the login
    # page). Set it on any internet-facing deployment; re-running the seed rotates existing accounts.
    demo_password: str | None = Field(None, repr=False)
    rate_limit_per_minute: int = 600
    approval_default_ttl_hours: int = 48
    data_retention_days_default: int = 365

    # --- LLM -------------------------------------------------------------
    # "auto" = the first provider with an API key (gemini, anthropic, openai), else the offline mock.
    llm_provider: Literal["auto", "mock", "anthropic", "openai", "gemini"] = "auto"
    # Providers tried, in order, when the primary is rate-limited, out of quota or down.
    # "auto" = every other provider that has an API key; "none" = no cross-provider failover.
    llm_fallback_providers: str = "auto"
    # Extra Gemini models tried after the primary Gemini model. On the free tier every model has
    # its own daily quota, so this multiplies the free capacity. Empty = none.
    gemini_fallback_models: str = "gemini-3.8-flash,gemini-3.5-flash-lite"
    # Models used when a provider is not the primary (the primary uses LLM_DEFAULT/FAST_MODEL).
    gemini_model: str = "gemini-3.6-flash"
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_fast_model: str = "claude-haiku-5-5"
    openai_model: str = "gpt-4o"
    openai_fast_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = Field(None, repr=False)
    openai_api_key: str | None = Field(None, repr=False)
    gemini_api_key: str | None = Field(None, repr=False)  # Google AI Studio key (Gemini Developer API)
    llm_default_model: str = "claude-opus-5-5"
    # Fast tier uses the same model at lower effort (usually matches a smaller model's
    # quality at similar cost); point LLM_FAST_MODEL elsewhere if you prefer.
    llm_fast_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_fast_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    copilot_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    copilot_max_iterations: int = 8
    copilot_max_tool_calls: int = 24
    llm_enable_fallbacks: bool = True
    custom_tools_allow_private_network: bool = False
    # Host headers accepted by the MCP endpoint (DNS-rebinding protection). Add your public host in production.
    mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*,testserver"
    llm_timeout_seconds: int = 60
    llm_max_output_tokens: int = 2048
    llm_max_input_chars: int = 60_000
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # --- Observability ---------------------------------------------------
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "opspilot-api"
    metrics_enabled: bool = True

    # --- Storage -----------------------------------------------------------
    document_storage_backend: Literal["local", "s3"] = "local"
    document_storage_path: str = "./storage"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    max_document_size_mb: int = 25

    # --- Billing / quotas ----------------------------------------------------
    default_monthly_workflow_quota: int = 5000
    default_monthly_token_quota: int = 5_000_000

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_psycopg3(cls, v: object) -> object:
        """Accept URLs as Neon/Heroku print them (postgres://, postgresql://): only psycopg 3 is installed."""
        if isinstance(v, str):
            v = v.strip().strip("'\"")
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _join_origins(cls, v: object) -> object:
        if isinstance(v, list | tuple):
            return ",".join(str(o) for o in v)
        if isinstance(v, str) and v.strip().startswith("["):  # tolerate a JSON list too
            import json

            try:
                return ",".join(str(o) for o in json.loads(v))
            except ValueError:
                return v
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_keys(self) -> dict[str, str | None]:
        return {"gemini": self.gemini_api_key, "anthropic": self.anthropic_api_key, "openai": self.openai_api_key}

    @property
    def effective_llm_provider(self) -> str:
        """The primary provider actually in use: one without its API key falls back to the mock."""
        if self.llm_provider == "auto":
            return next((p for p, k in self.llm_keys.items() if k), "mock")
        return self.llm_provider if self.llm_keys.get(self.llm_provider) else "mock"

    @property
    def llm_fallback_list(self) -> list[str]:
        """Cross-provider failover order (providers with a key, excluding the primary)."""
        primary = self.effective_llm_provider
        raw = self.llm_fallback_providers.strip().lower()
        if raw in {"none", "off", ""}:
            return []
        wanted = list(self.llm_keys) if raw == "auto" else [p.strip() for p in raw.split(",") if p.strip()]
        return [p for p in wanted if p != primary and self.llm_keys.get(p)]

    def models_for(self, provider: str) -> tuple[str, str]:
        """(default, fast) model ids for a provider. The primary uses LLM_DEFAULT_MODEL/LLM_FAST_MODEL
        when they belong to that provider's family; otherwise the per-provider defaults apply."""
        family = {"gemini": "gemini", "anthropic": "claude", "openai": "gpt"}.get(provider, "")
        if provider == self.effective_llm_provider and self.llm_default_model.startswith(family):
            fast = self.llm_fast_model if self.llm_fast_model.startswith(family) else self.llm_default_model
            return self.llm_default_model, fast
        return {
            "gemini": (self.gemini_model, self.gemini_model),
            "anthropic": (self.anthropic_model, self.anthropic_fast_model),
            "openai": (self.openai_model, self.openai_fast_model),
        }.get(provider, (self.llm_default_model, self.llm_fast_model))

    @property
    def is_transaction_pooler(self) -> bool:
        """Neon's pooled endpoint (PgBouncer, transaction mode): host contains '-pooler'."""
        return "-pooler." in self.database_url

    def validate_for_environment(self) -> list[str]:
        """Return a list of configuration problems for the current environment."""
        problems: list[str] = []
        if self.is_production:
            if self.secret_key.startswith("dev-only"):
                problems.append("SECRET_KEY must be set to a strong random value in production")
            if self.is_sqlite:
                problems.append("DATABASE_URL must point to PostgreSQL in production")
            if not self.encryption_key:
                problems.append("ENCRYPTION_KEY (Fernet) is required to store integration credentials")
            if self.llm_provider == "mock":
                problems.append("LLM_PROVIDER is 'mock' - agents will use heuristic fallbacks only")
            if self.allow_password_login and not self.oidc_issuer:
                problems.append("Password login is enabled without OIDC; configure OIDC_ISSUER for SSO")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        if self.llm_provider == "openai" and not self.openai_api_key:
            problems.append("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        if self.llm_provider == "auto" and self.effective_llm_provider == "mock":
            problems.append("LLM_PROVIDER=auto but no AI key is set (GEMINI_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY); agents use built-in logic")
        if self.llm_provider == "gemini":
            if not self.gemini_api_key:
                problems.append("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
            for name, model in (("LLM_DEFAULT_MODEL", self.llm_default_model), ("LLM_FAST_MODEL", self.llm_fast_model)):
                if not model.startswith("gemini"):
                    problems.append(f"LLM_PROVIDER=gemini but {name}={model}; set a Gemini model id (e.g. gemini-4-argon)")
        if self.worker_mode == "celery" and not self.redis_url:
            problems.append("WORKER_MODE=celery requires REDIS_URL")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
