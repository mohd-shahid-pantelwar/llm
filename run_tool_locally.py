import os
import psycopg2
import json

# Fetch tool code and valves
db_host = os.environ.get("POSTGRES_HOST", "10.0.10.131")
db_user = os.environ.get("POSTGRES_USER", "openwebui")
db_pass = os.environ.get("POSTGRES_PASSWORD", "openwebui")
db_name = os.environ.get("POSTGRES_DB", "rag")

conn = psycopg2.connect(dbname=db_name, user=db_user, password=db_pass, host=db_host)
cur = conn.cursor()
cur.execute("SELECT content, access_control FROM tools WHERE id=%s", ("soc-tool",))
row = cur.fetchone()
code = row[0]
access_control = row[1]
cur.close()
conn.close()

if isinstance(access_control, str):
    access_control = json.loads(access_control)

valves = access_control.get("valves", {})

# Create environment and execute code
tool_env = {}
exec(code, tool_env, tool_env)

# Instantiate and inject valves
tool_instance = tool_env['Tools']()
if hasattr(tool_instance, "valves"):
    for k, v in valves.items():
        setattr(tool_instance.valves, k, v)

# Run it!
print("Executing Native SOC Fetcher...")
result = tool_instance.fetch_soc_logs()
print("\n--- RESULTS ---")
print(result)
