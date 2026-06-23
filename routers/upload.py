from fastapi import APIRouter, UploadFile, File, HTTPException
from workers.queue import queue
from storage.minio_client import upload_file as minio_upload
import uuid

router = APIRouter(prefix="/api")

@router.post("/upload")
async def upload_file(file_name: UploadFile = File(...)):
    try:
        content = await file_name.read()
        text = content.decode("utf-8", errors="ignore")
        
        # 1. Upload raw file to MinIO
        unique_filename = f"{uuid.uuid4()}-{file_name.filename}"
        minio_upload(unique_filename, content)
        
        # 2. Queue for processing
        job = queue.enqueue(
            "workers.ingest_worker.process_file",
            unique_filename,
            text,
            job_timeout="2h"
        )
        
        return {"status": "queued", "job_id": job.id, "file_id": unique_filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))