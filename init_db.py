from database.db import get_conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255),
            email VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'user',
            status VARCHAR(50) DEFAULT 'active'
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            base_model_id VARCHAR(255),
            name VARCHAR(255) NOT NULL,
            params JSONB,
            meta JSONB,
            is_active BOOLEAN DEFAULT true,
            updated_at BIGINT,
            created_at BIGINT
        );
    """)

    # Insert a default admin user if none exists
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        # password is 'admin' hashed with bcrypt
        # We will use bcrypt to generate this in python but for now we just use a placeholder
        pass
        
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
