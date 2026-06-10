from redis import Redis
from rq import Queue

redis_conn = Redis(host="10.0.10.131", port=6379, db=0)
queue = Queue(
    connection=redis_conn,
    default_timeout=3600  # long ingestion jobs
)