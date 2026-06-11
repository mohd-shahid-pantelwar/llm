import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import get_conn

def test_db():
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Verify tables exist
    tables = ['prompts', 'skills', 'tools', 'knowledge']
    for table in tables:
        cur.execute(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table}')")
        exists = cur.fetchone()[0]
        print(f"Table '{table}' exists: {exists}")
        assert exists, f"Table '{table}' does not exist!"
        
    # 2. Test inserting into prompts
    print("\nTesting Insert...")
    cur.execute(
        "INSERT INTO prompts (id, user_id, title, description, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("test-prompt-id", 1, "Test Title", "Test Description", 123456789)
    )
    inserted_id = cur.fetchone()[0]
    print(f"Inserted prompt ID: {inserted_id}")
    
    # 3. Test selecting
    print("\nTesting Select...")
    cur.execute("SELECT title, description FROM prompts WHERE id = %s", (inserted_id,))
    row = cur.fetchone()
    print(f"Retrieved prompt: Title='{row[0]}', Description='{row[1]}'")
    assert row[0] == "Test Title"
    
    # 4. Test deleting
    print("\nTesting Delete...")
    cur.execute("DELETE FROM prompts WHERE id = %s RETURNING id", (inserted_id,))
    deleted_id = cur.fetchone()[0]
    print(f"Deleted prompt ID: {deleted_id}")
    
    conn.commit()
    cur.close()
    conn.close()
    print("\nAll database tests passed successfully!")

if __name__ == "__main__":
    test_db()
