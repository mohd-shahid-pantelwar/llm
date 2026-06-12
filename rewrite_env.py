import os
import glob
import re

files = {
    'services/ws_llm.py': ('OLLAMA_URL = "http://10.0.10.131:11434"', 'import os\nOLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")'),
    'services/embed_service.py': ('OLLAMA_URL = "http://10.0.10.131:11434"', 'import os\nOLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")'),
    'services/llm_service.py': ('OLLAMA_URL = "http://10.0.10.131:11434"', 'import os\nOLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")'),
    'database/redis.py': ('r = redis.Redis(host="10.0.10.131", port=6379, decode_responses=True)', 'import os\nr = redis.Redis(host=os.environ.get("REDIS_HOST", "10.0.10.131"), port=int(os.environ.get("REDIS_PORT", 6379)), decode_responses=True)'),
    'workers/queue.py': ('redis_conn = Redis(host="10.0.10.131", port=6379, db=0)', 'import os\nredis_conn = Redis(host=os.environ.get("REDIS_HOST", "10.0.10.131"), port=int(os.environ.get("REDIS_PORT", 6379)), db=0)'),
    'storage/minio_client.py': ('    "10.0.10.131:9000",\n    access_key="openwebui",\n    secret_key="openwebui"', '    os.environ.get("MINIO_URL", "10.0.10.131:9000"),\n    access_key=os.environ.get("MINIO_ACCESS_KEY", "openwebui"),\n    secret_key=os.environ.get("MINIO_SECRET_KEY", "openwebui")'),
}

for path, (target, replacement) in files.items():
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
        # if replacement not in content:
        if "import os" not in content and "os.environ.get" in replacement:
            # For minio client:
            if "minio_client.py" in path and "import os" not in content:
                content = "import os\n" + content
        content = content.replace(target, replacement)
        with open(path, 'w') as f:
            f.write(content)

# database/db.py
with open('database/db.py', 'r') as f:
    db_content = f.read()

if 'import os' not in db_content:
    db_content = "import os\n" + db_content

db_content = db_content.replace('host="10.0.10.131"', 'host=os.environ.get("DB_HOST", "10.0.10.131")')
db_content = db_content.replace('dbname="rag"', 'dbname=os.environ.get("DB_NAME", "rag")')
db_content = db_content.replace('user="openwebui"', 'user=os.environ.get("DB_USER", "openwebui")')
db_content = db_content.replace('password="openwebui"', 'password=os.environ.get("DB_PASSWORD", "openwebui")')

with open('database/db.py', 'w') as f:
    f.write(db_content)

# routers/models.py
with open('routers/models.py', 'r') as f:
    mod_content = f.read()
mod_content = mod_content.replace('res = requests.get("http://10.0.10.131:11434/api/tags")', 'OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")\n        res = requests.get(f"{OLLAMA_URL}/api/tags")')
with open('routers/models.py', 'w') as f:
    f.write(mod_content)

# main.py
with open('main.py', 'r') as f:
    main_content = f.read()
main_content = main_content.replace('allow_origins=["http://localhost:3000"]', 'allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")]')
if 'import os' not in main_content:
    main_content = "import os\n" + main_content
with open('main.py', 'w') as f:
    f.write(main_content)

print("Replacement complete.")
