import os
import psycopg2
import numpy as np


def get_conn():
    return psycopg2.connect(
        dbname=os.environ.get("DB_NAME", "rag"),
        user=os.environ.get("DB_USER", "openwebui"),
        password=os.environ.get("DB_PASSWORD", "openwebui"),
        host=os.environ.get("DB_HOST", "localhost"),
        port=5432
    )


