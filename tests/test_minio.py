import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from storage.minio_client import upload_file, get_file


file_name = "test.txt"
content = b"Hello MinIO"

upload_file(file_name, content)
print("Uploaded")

data = get_file(file_name)
print("Downloaded:", data.decode())