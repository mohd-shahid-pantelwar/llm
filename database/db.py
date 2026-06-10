import psycopg2
import numpy as np


def get_conn():
    return psycopg2.connect(
        dbname="rag",
        user="openwebui",
        password="openwebui",
        host="10.0.10.131",
        port=5432
    )






