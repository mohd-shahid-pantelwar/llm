from fastapi import APIRouter, UploadFile, File
from workers.queue import queue
from storage.minio_client import upload_file
from workers.queue import queue
router = APIRouter(prefix="/api")


@router.post("/upload")
async def upload_file(file_name, content):
    # DO NOT read full file into memory for large files
    content = await file_name.read(2 * 1024 * 1024)  # optional limit (2MB example)

    text = content.decode("utf-8", errors="ignore")

    job = queue.enqueue(
        "workers.ingest_worker.process_file",
        file_name.filename,
        text
    )

    return {"status": "queued", "job_id": job.id}