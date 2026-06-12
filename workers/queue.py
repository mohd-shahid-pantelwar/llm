from redis import Redis
from rq import Queue

import os
redis_conn = Redis(host=os.environ.get("REDIS_HOST", "10.0.10.131"), port=int(os.environ.get("REDIS_PORT", 6379)), db=0)
queue = Queue(
    connection=redis_conn,
    default_timeout=3600  # long ingestion jobs
)