
from database.db import get_conn
from services.ingest_service import ingest_document
from storage.minio_client import get_file


def process_file(file_name, content=None):

    # 1. fetch from MinIO
    file_bytes = get_file(file_name)
    text = file_bytes.decode("utf-8", errors="ignore")

    conn = get_conn()
    cur = conn.cursor()

    try:
        # Create table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                job_id VARCHAR(255) PRIMARY KEY,
                file_name VARCHAR(255),
                status VARCHAR(50),
                error TEXT,
                chunks_processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        
        # 2. Check if job exists and fetch checkpoint
        cur.execute("SELECT chunks_processed FROM ingestion_jobs WHERE file_name=%s", (file_name,))
        row = cur.fetchone()
        start_chunk = row[0] if row else 0

        if not row:
            cur.execute(
                "INSERT INTO ingestion_jobs (job_id, file_name, status, chunks_processed) VALUES (%s,%s,%s,%s)",
                (file_name, file_name, "processing", 0)
            )
        else:
            cur.execute(
                "UPDATE ingestion_jobs SET status=%s WHERE file_name=%s",
                ("processing", file_name)
            )
        conn.commit()

        print(f"\\n--- Job Queued (Checkpoint: {start_chunk}) ---")
        print(f"('{file_name}', 'processing')")
        print(f"------------------\\n")

        # 3. REAL INGESTION with Checkpoint Resuming
        ingest_document(text, file_name=file_name, start_chunk=start_chunk)

        # 4. mark success
        cur.execute(
            "UPDATE ingestion_jobs SET status=%s WHERE file_name=%s",
            ("done", file_name)
        )
        conn.commit()

        return "done"

    except Exception as e:
        conn.rollback()

        cur.execute(
            "UPDATE ingestion_jobs SET status=%s, error=%s WHERE file_name=%s",
            ("failed", str(e), file_name)
        )
        conn.commit()

        raise

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    from rq import Worker
    from workers.queue import redis_conn
    
    print("Starting RQ worker for document ingestion...")
    worker = Worker(['openui_ingestion'], connection=redis_conn)
    worker.work()