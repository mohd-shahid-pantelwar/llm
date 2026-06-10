from fastapi import APIRouter
import requests

router = APIRouter(prefix="/api")

@router.get("/models")
def get_models():
    res = requests.get("http://10.0.10.131:11434/api/tags")
    data = res.json()

    return {
        "models": data.get("models", [])
    }