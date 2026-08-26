from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.cycle import router as cycle_router
from app.api.v1.logs import router as logs_router
from app.api.v1.therapy import router as therapy_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(cycle_router)
api_v1_router.include_router(logs_router)
api_v1_router.include_router(therapy_router)
