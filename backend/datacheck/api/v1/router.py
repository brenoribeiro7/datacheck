from fastapi import APIRouter

from datacheck.api.v1.auth import router as auth_router
from datacheck.api.v1.datasets import router as datasets_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(datasets_router)
