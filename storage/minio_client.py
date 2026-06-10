from minio import Minio
import io

client = Minio(
    "10.0.10.131:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    secure=False
)

BUCKET = "documents"


def get_file(file_name):
    response = client.get_object(BUCKET, file_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def upload_file(file_name, file_bytes):
    data_stream = io.BytesIO(file_bytes)

    client.put_object(
        BUCKET,
        file_name,
        data=data_stream,
        length=len(file_bytes),
        content_type="application/octet-stream"
    )