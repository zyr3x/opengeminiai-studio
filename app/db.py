import sqlite3
import os

UPLOAD_FOLDER = "var/uploads"
# --- Database setup ---
DATABASE_FILE = "var/data/chats.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Ensure data and upload directories exist
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    if os.path.exists(DATABASE_FILE) and os.path.getsize(DATABASE_FILE) > 0:
        return

    print("Initializing database...")
    conn = get_db_connection()
    conn.execute('PRAGMA foreign_keys = ON;')
    conn.execute('''
        CREATE TABLE chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.execute('''
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL, -- user, model, or tool
            parts TEXT NOT NULL, -- JSON list of parts (text or file references)
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
        );
    ''')
    conn.commit()
    conn.close()
    print("Database initialized.")

init_db()