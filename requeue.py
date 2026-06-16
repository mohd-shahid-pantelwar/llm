import sys
import os
from database.db import get_conn
from storage.minio_client import get_file
from workers.queue import queue
from rq.job import Job

conn = get_conn()
cur = conn.cursor()

# Find the last failed or stuck job
cur.execute("SELECT file_name, chunks_processed FROM ingestion_jobs WHERE status != 'done' ORDER BY created_at DESC LIMIT 1")
row = cur.fetchone()

if not row:
    print("No stuck or failed jobs found!")
    sys.exit(0)

file_name = row[0]
chunks_processed = row[1]

print(f"Found interrupted job: {file_name}")
print(f"It previously completed {chunks_processed} chunks.")

# Fetch content from Minio to requeue
try:
    file_bytes = get_file(file_name)
    content = file_bytes.decode("utf-8", errors="ignore")
    
    # Requeue the job
    job = queue.enqueue("workers.ingest_worker.process_file", file_name, content)
    
    print(f"✅ Successfully RE-QUEUED job! It will automatically resume at chunk {chunks_processed}.")
    print(f"New RQ Job ID: {job.id}")
except Exception as e:
    print(f"Failed to fetch file from Minio: {e}")

cur.close()
conn.close()
