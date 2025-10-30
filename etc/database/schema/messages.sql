CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL, -- user, model, or tool
            parts TEXT NOT NULL, -- JSON list of parts (text or file references)
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
);