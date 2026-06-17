#!/bin/bash

echo "Starting Global Knowledge Base embedding restoration..."

docker exec rag-api python -c '
import psycopg2
from redis import Redis
from rq import Queue

print("Connecting to PostgreSQL...")
conn = psycopg2.connect(dbname="rag", user="openwebui", password="openwebui", host="10.0.10.131")
cur = conn.cursor()

# 1. Select every file you uploaded globally that is NOT one of the massive SOC batch files
cur.execute("SELECT file_name FROM ingestion_jobs WHERE file_name NOT LIKE %s", ("%soc_batch%",))
files = cur.fetchall()

print("Connecting to Redis RQ queue...")
q = Queue("openui_ingestion", connection=Redis(host="10.0.10.131", port=6379))

queued_count = 0

# 2. Loop through every file, reset its checkpoint to 0, and throw it back into the worker queue
for (fname,) in files:
    cur.execute("UPDATE ingestion_jobs SET chunks_processed=0, status=%s WHERE file_name=%s", ("pending", fname))
    q.enqueue("workers.ingest_worker.process_file", fname)
    queued_count += 1

conn.commit()
print(f"\n✅ Successfully queued {queued_count} files for background embedding!")
print("You can monitor the progress by running: docker logs -f rag-worker")
'
