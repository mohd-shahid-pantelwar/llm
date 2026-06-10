from fastapi import APIRouter
from workers.queue import queue

router = APIRouter(prefix="/api")


@router.get("/job/{job_id}")
def get_job(job_id: str):
    job = queue.fetch_job(job_id)

    if not job:
        return {"status": "not_found"}

    return {
        "id": job.id,
        "status": job.get_status(),
        "result": job.result
    }