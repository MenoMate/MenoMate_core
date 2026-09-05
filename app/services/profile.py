import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.profile import Profile


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    """
    Fetch existing user profile or initialize a baseline profile record.
    Designed to prevent race conditions during concurrent startup requests.
    """
    stmt = select(Profile).where(Profile.user_id == user_id)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()
    if profile is not None:
        return profile

    try:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile
    except Exception:
        await db.rollback()
        # In case another concurrent request committed the profile first
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is not None:
            return profile
        raise
