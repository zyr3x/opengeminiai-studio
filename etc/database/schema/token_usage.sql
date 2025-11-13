CREATE TABLE IF NOT EXISTS token_usage (
            date TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            model_name TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, key_hash, model_name)
);