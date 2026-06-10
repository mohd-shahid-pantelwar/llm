from fastapi import APIRouter, status

router = APIRouter(prefix="/api")

@router.get("/health")
async def check_health():
    """
    Called by chatApiService.checkHealth() to verify connection.
    """
    return {"status": "ok"}
