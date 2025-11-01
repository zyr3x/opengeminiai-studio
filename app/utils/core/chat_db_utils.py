import os
import shutil
from app.db import get_db_connection, UPLOAD_FOLDER
from app.utils.core import logging, tools as utils

def get_all_chats():
    conn = get_db_connection()
    chats = conn.execute('SELECT id, title FROM chats ORDER BY created_at DESC').fetchall()
    conn.close()
    return [dict(c) for c in chats]

def create_new_chat():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chats (title) VALUES ('New Chat')")
    new_chat_id = cursor.lastrowid
    conn.commit()
    new_chat = {'id': new_chat_id, 'title': 'New Chat'}
    conn.close()
    return new_chat

def update_chat_title_in_db(chat_id: int, new_title: str):
    conn = get_db_connection()
    conn.execute('UPDATE chats SET title = ? WHERE id = ?', (new_title, chat_id))
    conn.commit()
    conn.close()

def delete_chat_and_files(chat_id: int):
    try:
        chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
        if os.path.exists(chat_upload_folder):
            shutil.rmtree(chat_upload_folder)
    except OSError as e:
        logging.log(f"Error deleting files for chat {chat_id}: {e}")

    conn = get_db_connection()
    conn.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
    conn.commit()
    conn.close()

def get_messages_for_chat(chat_id: int):
    conn = get_db_connection()
    messages = conn.execute(
        'SELECT id, role, parts FROM messages WHERE chat_id = ? ORDER BY id ASC',
        (chat_id,)
    ).fetchall()
    conn.close()

    formatted_messages = []
    for db_message in messages:
        role = 'assistant' if db_message['role'] == 'model' else db_message['role']
        message_data = utils.format_message_parts_for_ui(db_message['parts'])

        if message_data['content'] or message_data['files']:
            formatted_messages.append({'id': db_message['id'], 'role': role, **message_data})
    return formatted_messages

def delete_message_from_db(message_id: int):
    conn = get_db_connection()
    conn.execute('DELETE FROM messages WHERE id = ?', (message_id,))
    conn.commit()
    conn.close()
