"""Application settings loaded from environment via pydantic-settings."""
 
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
 
from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
 
# backend/ — stable path regardless of process working directory
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _BACKEND_ROOT / ".env"
 
 
class Settings(BaseSettings):
    """Runtime configuration for the FastAPI application and database layer."""
 
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
 
    app_name: str = "Gmail RAG API"
    debug: bool = False
 
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gmail_rag",
        description="Async SQLAlchemy URL (postgresql+asyncpg://...)",
    )
 
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allowed CORS origins (comma-separated in env)",
    )
 
    db_check_on_startup: bool = Field(
        default=True,
        description="Verify database connectivity during application startup",
    )
 
    # Google OAuth (required for auth routes)
    google_client_id: str = Field(min_length=1)
    google_client_secret: str = Field(min_length=1)
    google_redirect_uri: str = Field(
        min_length=1,
        description="Must match Google Cloud Console authorized redirect URI",
    )
 
    # JWT for application sessions (distinct from Google OAuth tokens)
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, ge=1)
 
    # Fernet key for encrypting Google OAuth tokens at rest (from Fernet.generate_key())
    token_encryption_key: str = Field(min_length=1)
 
    # Session cookie (JWT stored here after OAuth; not in URL)
    auth_cookie_name: str = Field(default="access_token")
    auth_cookie_secure: bool = Field(
        default=False,
        description="Set true in production (HTTPS). Must be false for local HTTP dev.",
    )
 
    # Post-OAuth browser redirect (must match allowlist below)
    frontend_oauth_redirect_url: str = Field(
        default="http://localhost:3000/auth/callback",
        description="Frontend URL after successful OAuth (no tokens in query string)",
    )
 
    allowed_frontend_redirect_urls: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000/auth/callback"],
        description="Allowlist of permitted FRONTEND_OAUTH_REDIRECT_URL values",
    )
 
    oauth_state_max_age_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Max age for signed OAuth state parameter",
    )
 
    # Gmail sync (MVP synchronous ingestion)
    gmail_sync_max_messages: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Max messages to fetch per sync job (MVP cap)",
    )
    gmail_api_request_timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
 
    # Text chunking (token-based; tiktoken cl100k_base)
    chunk_size: int = Field(default=500, ge=64, le=8192, description="Tokens per chunk")
    chunk_overlap: int = Field(
        default=100,
        ge=0,
        le=1024,
        description="Overlapping tokens between consecutive chunks",
    )
 
    # OpenAI (required for Phase 6 embeddings)
    openai_api_key: str = Field(min_length=1)
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dimensions: int = Field(default=1536)
 
    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
 
    @field_validator("allowed_frontend_redirect_urls", mode="before")
    @classmethod
    def parse_allowed_redirect_urls(cls, value: object) -> object:
        if isinstance(value, str):
            return [url.strip() for url in value.split(",") if url.strip()]
        return value
 
    @field_validator("token_encryption_key")
    @classmethod
    def validate_token_encryption_key(cls, value: str) -> str:
        try:
            Fernet(value.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY must be a valid Fernet key "
                '(generate: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())")'
            ) from exc
        return value
 
    @model_validator(mode="after")
    def validate_security_config(self) -> Settings:
        """Startup validation for redirect URL allowlist and secret separation."""
        if self.token_encryption_key == self.jwt_secret_key:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY must differ from JWT_SECRET_KEY"
            )
 
        redirect = self.frontend_oauth_redirect_url.strip()
        if redirect not in self.allowed_frontend_redirect_urls:
            raise ValueError(
                "FRONTEND_OAUTH_REDIRECT_URL must be listed in "
                f"ALLOWED_FRONTEND_REDIRECT_URLS. Allowed: "
                f"{self.allowed_frontend_redirect_urls}"
            )
 
        parsed = urlparse(redirect)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "FRONTEND_OAUTH_REDIRECT_URL must be a valid http(s) URL"
            )
 
        for url in self.allowed_frontend_redirect_urls:
            parsed_allowed = urlparse(url)
            if parsed_allowed.scheme not in ("http", "https") or not parsed_allowed.netloc:
                raise ValueError(
                    f"Invalid URL in ALLOWED_FRONTEND_REDIRECT_URLS: {url}"
                )
 
        if not self.debug and not self.auth_cookie_secure:
            raise ValueError(
                "AUTH_COOKIE_SECURE must be true when DEBUG is false (production)"
            )
 
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
 
        return self
 
 
@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance (one per process)."""
    return Settings()
 
 
settings = get_settings()