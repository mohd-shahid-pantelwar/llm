from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from workers.queue import queue
from storage.minio_client import upload_file as minio_upload
from database.db import get_conn
import os
import uuid
import json
import time
from datetime import datetime
import redis
from pydantic import BaseModel

from routers.users import get_admin_user

router = APIRouter(prefix="/api")

class DocumentSettings(BaseModel):
    chunkSize: str
    chunkOverlap: str
    pdfExtractionEngine: str
    embeddingModel: str
    embeddingUrl: str
    embeddingKey: str
    topK: str
    ragTemplate: str
    minScore: str = "0.6"
    webFallback: str = "true"
    webCacheTTLDays: str = "7"

def get_redis():
    return redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=int(os.environ.get("REDIS_PORT", 6379)), decode_responses=True)

@router.post("/admin/settings/documents")
async def save_document_settings(settings: DocumentSettings, admin: dict = Depends(get_admin_user)):
    try:
        r = get_redis()
        r.set("admin:settings:embeddingModel", settings.embeddingModel)
        r.set("admin:settings:chunkSize", settings.chunkSize)
        r.set("admin:settings:chunkOverlap", settings.chunkOverlap)
        r.set("admin:settings:topK", settings.topK)
        r.set("admin:settings:ragTemplate", settings.ragTemplate)
        r.set("admin:settings:pdfExtractionEngine", settings.pdfExtractionEngine)
        r.set("admin:settings:minScore", settings.minScore)
        r.set("admin:settings:webFallback", settings.webFallback)
        r.set("admin:settings:webCacheTTLDays", settings.webCacheTTLDays)
        if settings.embeddingUrl:
            r.set("admin:settings:embeddingUrl", settings.embeddingUrl)
        if settings.embeddingKey:
            r.set("admin:settings:embeddingKey", settings.embeddingKey)

        return {"status": "success", "message": "Settings saved to Redis"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/settings/documents")
async def get_document_settings(admin: dict = Depends(get_admin_user)):
    try:
        r = get_redis()
        keys = ["embeddingModel", "chunkSize", "chunkOverlap", "topK", "ragTemplate", "embeddingUrl", "pdfExtractionEngine", "minScore", "webFallback", "webCacheTTLDays"]
        # embeddingKey is intentionally omitted: never echo the secret back to the UI.
        # The save endpoint only overwrites it when a non-empty value is submitted.
        return {k: r.get(f"admin:settings:{k}") for k in keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/reindex")
async def reindex_vector_db(admin: dict = Depends(get_admin_user)):
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # 1. Wipe vector db and reset jobs
        cur.execute("DELETE FROM documents")
        cur.execute("UPDATE ingestion_jobs SET status='pending', chunks_processed=0, error=NULL")
        
        # 2. Re-queue all files
        cur.execute("SELECT file_name FROM ingestion_jobs")
        rows = cur.fetchall()
        
        for r in rows:
            file_name = r[0]
            # Enqueue the job without text, process_file will fetch from minio
            queue.enqueue(
                "workers.ingest_worker.process_file",
                file_name,
                job_timeout="2h"
            )
            
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "success", "message": f"Wiped DB and queued {len(rows)} files for reindexing."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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