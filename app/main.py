from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_v1_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Safe startup schema creation (e.g. for dev/sqlite/test environments)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # In remote Postgres environments without DDL permissions, logs and continues
        print(f"Database schema initialization warning: {e}")
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="MenoMate Core Autonomous Menstrual Wellness Intelligence API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API v1
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.PROJECT_NAME,
            "version": "1.0.0",
        }

    @app.get("/", tags=["Health"])
    async def root():
        return {
            "message": "Welcome to MenoMate Core API",
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
