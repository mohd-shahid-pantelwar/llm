import os
import re
from storage.minio_client import client, BUCKET
from services.embed_service import embed
from database.db import get_conn
import numpy as np

def fix_database():
    print("Fetching 33 chunked files from MinIO...")
    objects = client.list_objects(BUCKET, prefix="chunked_")
    
    conn = get_conn()
    cur = conn.cursor()
    
    success = 0
    
    for obj in objects:
        filename = obj.object_name
        # e.g., chunked_Wazuh_Apparmor_DENIED.json
        clean_name = filename.replace("chunked_", "").replace(".json", "")
        
        parts = clean_name.split("_", 1)
        if len(parts) == 2:
            origin = parts[0]
            # Replace underscores back to spaces for readability
            rule_desc = parts[1].replace("_", " ")
        else:
            origin = clean_name
            rule_desc = "Logs"
            
        header_text = f"Security Logs for {origin}. Alert Type: {rule_desc}"
        db_chunk_content = f"FILE_REFERENCE:[{filename}] {header_text}"
        
        try:
            print(f"Embedding header: {header_text}")
            header_embedding = embed([header_text])[0]
            
            # Handle if embed returns a numpy array or python list
            if isinstance(header_embedding, np.ndarray):
                header_embedding = header_embedding.tolist()
                
            cur.execute(
                """
                INSERT INTO documents (chunk, embedding, content_tsv) 
                VALUES (%s, %s::vector, to_tsvector('english', %s))
                """, 
                (db_chunk_content, header_embedding, header_text)
            )
            success += 1
        except Exception as e:
            print(f"Failed to embed {filename}: {e}")
            
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\\n✅ Successfully fixed database! Embedded and inserted {success} chunk headers.")

if __name__ == "__main__":
    fix_database()
