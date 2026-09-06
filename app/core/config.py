from typing import List, Optional, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_PLACEHOLDER_SECRETS = {
    "your-supabase-jwt-secret",
    "your-supabase-jwt-secret-here",
    "change-me",
    "secret",
    "placeholder",
}

INSECURE_PLACEHOLDER_URLS = {
    "https://your-project-ref.supabase.co",
    "http://your-project-ref.supabase.co",
}


class Settings(BaseSettings):
    PROJECT_NAME: str = "MenoMate Core Backend"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    SUPABASE_URL: str
    SUPABASE_JWT_SECRET: Optional[str] = None
    SUPABASE_JWKS_URL: Optional[str] = None

    ALLOWED_ORIGINS: Union[List[str], str] = "*"
    AUTO_CREATE_TABLES: bool = False

    @property
    def jwks_url(self) -> str:
        if self.SUPABASE_JWKS_URL and self.SUPABASE_JWKS_URL.strip():
            return self.SUPABASE_JWKS_URL.strip()
        return f"{self.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            if v.strip() == "*":
                return ["*"]
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["*"]

    @model_validator(mode="after")
    def validate_security_credentials(self) -> "Settings":
        url = (self.SUPABASE_URL or "").strip().rstrip("/")
        if not url or url in INSECURE_PLACEHOLDER_URLS or "your-project-ref" in url:
            raise ValueError(
                "Insecure configuration: SUPABASE_URL is missing or set to an unconfigured placeholder. "
                "A real Supabase project URL is required for production authentication."
            )

        if self.SUPABASE_JWT_SECRET is not None and self.SUPABASE_JWT_SECRET.strip():
            secret = self.SUPABASE_JWT_SECRET.strip()
            if secret in INSECURE_PLACEHOLDER_SECRETS or "your-supabase-jwt-secret" in secret:
                raise ValueError(
                    "Insecure configuration: SUPABASE_JWT_SECRET is set to an unconfigured placeholder. "
                    "A secure production JWT secret is required when symmetric signing is configured."
                )

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
