from database.db import get_conn


def update_progress(job_id: str, done: int, total: int):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE ingestion_jobs
        SET status=%s
        WHERE job_id=%s
    """, (f"{done}/{total}", job_id))

    conn.commit()
    cur.close()
    conn.close()