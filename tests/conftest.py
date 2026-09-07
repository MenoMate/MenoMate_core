import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator
import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from datetime import datetime, timedelta, timezone

# Ensure root directory is on python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set dummy test credentials & database before settings initialization
os.environ["SUPABASE_JWT_SECRET"] = "test-secret-key-12345678901234567890"
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = ""

from app.core.config import settings
settings.SUPABASE_JWT_SECRET = "test-secret-key-12345678901234567890"
settings.SUPABASE_URL = "https://test-project.supabase.co"
settings.GROQ_API_KEY = None

import app.models  # Ensure all models are registered with Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.ai_provider import set_ai_provider


@pytest.fixture(autouse=True)
def reset_ai_provider_override():
    set_ai_provider(None)
    yield
    set_ai_provider(None)

TEST_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
ANOTHER_USER_ID = uuid.UUID("99999999-8888-7777-6666-555555555555")

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
test_async_session = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session() as session:
        yield session


def make_token(
    user_id: uuid.UUID = TEST_USER_ID,
    aud: str = "authenticated",
    iss: str = None,
    exp: int = None,
) -> str:
    if iss is None:
        iss = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"
    if exp is None:
        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(user_id),
        "aud": aud,
        "iss": iss,
        "exp": exp,
        "role": "authenticated",
        "email": "user@menomate.health",
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def auth_headers() -> dict:
    token = make_token(TEST_USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_user_auth_headers() -> dict:
    token = make_token(ANOTHER_USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        async with test_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
