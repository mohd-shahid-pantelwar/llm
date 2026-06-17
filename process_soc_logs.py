import os
import json
import re
from storage.minio_client import get_file, upload_file, client, BUCKET
from services.embed_service import embed
from database.db import get_conn
from psycopg2.extras import execute_values

def safe_filename(name):
    """Clean string to be safe for MinIO filenames"""
    if not name:
        return "Unknown"
    return re.sub(r'[^\w\s-]', '', str(name)).replace(' ', '_')

def delete_minio_file(file_name):
    client.remove_object(BUCKET, file_name)

def process_soc_logs(file_name):
    print(f"\\n--- Processing Massive SOC JSON: {file_name} ---")
    
    # 1. Fetch massive file
    file_bytes = get_file(file_name)
    text = file_bytes.decode("utf-8", errors="ignore")
    
    print(f"File loaded into memory. Total size: {len(text) // (1024*1024)} MB")
    
    buckets = {}
    
    print("Parsing JSON stream directly...")
    
    decoder = json.JSONDecoder()
    pos = 0
    total_parsed = 0
    
    # Fast regex to skip non-JSON garbage (like array brackets or commas between objects)
    whitespace_re = re.compile(r'[\s,\[\]]+')
    
    while pos < len(text):
        # Skip whitespaces, commas, or array brackets between objects
        match = whitespace_re.match(text, pos)
        if match:
            pos = match.end()
            
        if pos >= len(text):
            break
            
        try:
            # ZERO COPY JSON parsing! Very fast.
            log_obj, pos = decoder.raw_decode(text, pos)
            total_parsed += 1
            
            origin = log_obj.get("_origin", "Unknown")
            rule_desc = "Unknown_Category"
            
            # Wazuh Parsing
            if "rule" in log_obj and "description" in log_obj["rule"]:
                rule_desc = log_obj["rule"]["description"]
            
            # OPNsense Parsing
            elif origin == "OPNsense-Firewall" and "full_log" in log_obj:
                match = re.search(r"OPNsense\.\S+\s+(\w+)", log_obj["full_log"])
                if match:
                    rule_desc = match.group(1).capitalize() + " Log"
                else:
                    rule_desc = "General Firewall Log"
            
            # Extract date for chronological chunking
            date_str = "Unknown_Date"
            timestamp = log_obj.get("timestamp", "")
            if timestamp:
                # Extract YYYY-MM-DD from strings like "2024-02-29 14:35:22"
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", timestamp)
                if date_match:
                    date_str = date_match.group(1)

            # Combine to make a grouping key
            bucket_key = f"{date_str}_{origin}_{rule_desc}"
            
            if bucket_key not in buckets:
                buckets[bucket_key] = {
                    "header": f"Security Logs for {origin}. Date: {date_str}. Alert Type: {rule_desc}",
                    "logs": []
                }
            
            buckets[bucket_key]["logs"].append(log_obj)
            
        except Exception as e:
            # If parsing fails, try to find the next opening brace
            next_brace = text.find('{', pos + 1)
            if next_brace != -1:
                pos = next_brace
            else:
                break
            continue
            
    print(f"Successfully parsed {total_parsed} log objects into {len(buckets)} distinct alert buckets!")
    
    # 3. Create tiny files and embed headers
    conn = get_conn()
    cur = conn.cursor()
    
    successful_uploads = 0
    
    for bucket_key, data in buckets.items():
        # Generate safe filename for this specific chunk
        chunk_file_name = f"chunked_{safe_filename(bucket_key)}.json"
        
        # Convert logs back to JSON array
        chunk_bytes = json.dumps(data["logs"], indent=2).encode('utf-8')
        
        try:
            # Upload the tiny file to MinIO
            upload_file(chunk_file_name, chunk_bytes)
            successful_uploads += 1
            
            # Now, embed ONLY the header description!
            header_text = data["header"]
            header_embedding = embed([header_text])[0]
            
            # Insert the header into the DB, but store the MinIO filename so RAG can fetch it!
            # We prefix the chunk text with the filename so the RAG router knows what file to pull
            db_chunk_content = f"FILE_REFERENCE:[{chunk_file_name}] {header_text}"
            
            cur.execute(
                """
                INSERT INTO documents (chunk, embedding, content_tsv) 
                VALUES (%s, %s::vector, to_tsvector('english', %s))
                """, 
                (db_chunk_content, header_embedding if isinstance(header_embedding, list) else header_embedding.tolist(), header_text)
            )
            
        except Exception as e:
            print(f"Error processing bucket {bucket_key}: {e}")
            
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\\n✅ Successfully uploaded {successful_uploads}/{len(buckets)} chunk files to MinIO.")
    
    # 4. Safely delete the massive file ONLY if all chunks were successfully created
    if successful_uploads == len(buckets) and successful_uploads > 0:
        print(f"All chunks verified. Safely deleting original massive file: {file_name}")
        delete_minio_file(file_name)
    else:
        print(f"⚠️ Warning: Only {successful_uploads} out of {len(buckets)} uploaded. Keeping original file for safety.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        process_soc_logs(sys.argv[1])
    else:
        print("Please provide a filename. Example: python process_soc_logs.py 177ee...soc_batch.json")
