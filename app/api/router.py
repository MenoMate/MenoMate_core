from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.profile import router as profile_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.cycles import router as cycles_router
from app.api.v1.logs import router as logs_router
from app.api.v1.summary import router as summary_router
from app.api.v1.devices import router as devices_router
from app.api.v1.therapy import router as therapy_router
from app.api.v1.care import router as care_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(onboarding_router)
api_v1_router.include_router(cycles_router)
api_v1_router.include_router(logs_router)
api_v1_router.include_router(summary_router)
api_v1_router.include_router(devices_router)
api_v1_router.include_router(therapy_router)
api_v1_router.include_router(care_router)
