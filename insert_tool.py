import sys, os, json
sys.path.append('/app')
from database.db import get_conn
import uuid

conn = get_conn()
cur = conn.cursor()

# Get soc-tool access_control to copy the credentials
cur.execute("SELECT access_control FROM tools WHERE id='soc-tool'")
row = cur.fetchone()
if not row:
    print("Could not find soc-tool")
    sys.exit(1)

access_control_json = row[0]
if isinstance(access_control_json, str):
    access_control = json.loads(access_control_json)
else:
    access_control = access_control_json

tool_id = "agent-inventory-tool"
user_id = 1 # Must be an integer

with open('/app/tools/agent_inventory_tool.py', 'r') as f:
    content = f.read()

# Insert or update
cur.execute("SELECT id FROM tools WHERE id=%s", (tool_id,))
if cur.fetchone():
    cur.execute("UPDATE tools SET content=%s, access_control=%s WHERE id=%s", (content, json.dumps(access_control), tool_id))
    print("Updated existing agent-inventory-tool.")
else:
    cur.execute(
        "INSERT INTO tools (id, user_id, title, description, content, access_control) VALUES (%s, %s, %s, %s, %s, %s)",
        (tool_id, user_id, "agent-inventory-tool", "Wazuh Agent Inventory", content, json.dumps(access_control))
    )
    print("Inserted new agent-inventory-tool.")

conn.commit()
cur.close()
conn.close()
