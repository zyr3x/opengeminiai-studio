import sqlite3
import os
UPLOAD_FOLDER = "var/uploads"
DATABASE_FILE = "var/data/chats.db"
def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("Checking/Initializing database tables...")
    conn = get_db_connection()
    conn.execute('PRAGMA foreign_keys = ON;')
    conn.execute(f'{get_schema("chats")}')
    conn.execute(f'{get_schema("messages")}')
    conn.execute(f'{get_schema("token_usage")}')
    conn.commit()
    conn.close()
    print("Database check/initialization complete.")
def get_schema(name):
    with open(os.path.realpath(os.path.expanduser(f"etc/database/schema/{name}.sql")), 'r', encoding='utf-8',
              errors='ignore') as f:
        return f.read()