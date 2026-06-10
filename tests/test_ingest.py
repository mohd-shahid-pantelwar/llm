import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.ingest_service import ingest_document


text = """
Docker is a container platform.
It isolates applications.
"""

result = ingest_document(text)

print(result)