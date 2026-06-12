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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            background_image VARCHAR(255),
            system_prompt TEXT,
            knowledge TEXT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            model_id VARCHAR(255) NOT NULL,
            messages JSONB NOT NULL DEFAULT '[]'::jsonb,
            is_archived BOOLEAN DEFAULT false,
            pinned BOOLEAN DEFAULT false,
            folder_id VARCHAR(255) REFERENCES folders(id) ON DELETE SET NULL,
            updated_at BIGINT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            content TEXT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            content TEXT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tools (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            content TEXT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            content TEXT,
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            message_id VARCHAR(255) NOT NULL,
            chat_id VARCHAR(255) REFERENCES chats(id) ON DELETE CASCADE,
            model_name VARCHAR(255),
            type VARCHAR(10) NOT NULL CHECK (type IN ('like', 'dislike')),
            rating INTEGER CHECK (rating BETWEEN 1 AND 10),
            reasons JSONB DEFAULT '[]'::jsonb,
            details TEXT,
            tag VARCHAR(255),
            created_at BIGINT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id VARCHAR(255) PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            content TEXT,
            color VARCHAR(255),
            chat_history JSONB DEFAULT '[]'::jsonb,
            updated_at BIGINT,
            created_at BIGINT
        );
    """)

    conn.commit()

    try:
        cur.execute("ALTER TABLE notes ADD COLUMN chat_history JSONB DEFAULT '[]'::jsonb;")
    except Exception:
        conn.rollback()
    else:
        conn.commit()

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
