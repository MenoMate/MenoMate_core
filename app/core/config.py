from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "MenoMate Core Backend"
    API_V1_STR: str = "/api/v1"
    
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    SUPABASE_JWT_SECRET: str = "your-supabase-jwt-secret"
    SUPABASE_URL: str = "https://your-project-ref.supabase.co"
    
    ALLOWED_ORIGINS: Union[List[str], str] = "*"
    
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
