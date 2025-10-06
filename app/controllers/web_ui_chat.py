"""
Flask routes for the web chat UI, including the main page and direct chat API.
"""
import base64
import json
import shutil
import requests
import os
from flask import Blueprint, request, jsonify, Response, send_from_directory
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
from werkzeug.utils import secure_filename

from app.config import config
from app import mcp_handler
from app import utils
from app.db import get_db_connection, UPLOAD_FOLDER


web_ui_chat_bp = Blueprint('web_ui_chat', __name__)


# --- Chat Management API Routes ---
@web_ui_chat_bp.route('/api/chats', methods=['GET'])
def get_chats():
    conn = get_db_connection()
    chats = conn.execute('SELECT id, title FROM chats ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(c) for c in chats])

@web_ui_chat_bp.route('/api/chats', methods=['POST'])
def create_chat():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chats (title) VALUES ('New Chat')")
    new_chat_id = cursor.lastrowid
    conn.commit()
    new_chat = {'id': new_chat_id, 'title': 'New Chat'}
    conn.close()
    return jsonify(new_chat), 201

@web_ui_chat_bp.route('/api/chats/<int:chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    """
    Deletes a chat and its associated messages and files.
    """
    # 1. Delete associated files
    try:
        chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
        if os.path.exists(chat_upload_folder):
            shutil.rmtree(chat_upload_folder)
    except OSError as e:
        print(f"Error deleting files for chat {chat_id}: {e}")

    # 2. Delete chat from the database (messages are deleted via CASCADE)
    conn = get_db_connection()
    conn.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True}), 200

@web_ui_chat_bp.route('/api/chats/<int:chat_id>/messages', methods=['GET'])
def get_chat_messages(chat_id):
    conn = get_db_connection()
    messages = conn.execute(
        'SELECT role, parts FROM messages WHERE chat_id = ? ORDER BY id ASC',
        (chat_id,)
    ).fetchall()
    conn.close()

    formatted_messages = []
    for db_message in messages:
        role = 'assistant' if db_message['role'] == 'model' else db_message['role']
        message_data = {'role': role, 'content': '', 'files': []}
        try:
            parts = json.loads(db_message['parts'])
            text_parts = []
            for part in parts:
                if 'text' in part:
                    text_parts.append(part['text'])
                elif 'file_data' in part:
                    file_path = part['file_data']['path']
                    # Create a relative path for the URL
                    relative_path = os.path.relpath(file_path, UPLOAD_FOLDER)
                    file_url = f"/uploads/{relative_path.replace(os.sep, '/')}"
                    message_data['files'].append({
                        'url': file_url,
                        'mimetype': part['file_data']['mime_type'],
                        'name': os.path.basename(file_path)
                    })
            message_data['content'] = " ".join(text_parts).strip()

            if message_data['content'] or message_data['files']:
                formatted_messages.append(message_data)
        except (json.JSONDecodeError, TypeError):
            continue
    return jsonify(formatted_messages)

@web_ui_chat_bp.route('/api/generate_image', methods=['POST'])
def generate_image_api():
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        chat_id = request.form.get('chat_id', type=int)
        model = request.form.get('model', 'gemini-1.5-pro-latest')
        prompt = request.form.get('prompt', '')

        if not all([chat_id, model, prompt]):
            return jsonify({"error": "chat_id, model, and prompt are required"}), 400

        # 1. Save user message to DB
        user_parts = [{"text": prompt}]
        db_conn = get_db_connection()
        db_conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)', (chat_id, 'user', json.dumps(user_parts)))
        db_conn.commit()
        db_conn.close()

        # 2. Call the image generation model via non-streaming API
        IMAGE_GEN_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:generateContent"
        headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
        request_data = {
            "contents": [{"parts": [{"text": f"Generate an image of: {prompt}"}]}],
        }

        response = requests.post(IMAGE_GEN_URL, headers=headers, json=request_data, timeout=300)
        response.raise_for_status()
        response_data = response.json()

        # 3. Process the response
        parts = response_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])

        image_data = None
        mime_type = None

        # Try to find inline image data first
        inline_part = next((p for p in parts if 'inline_data' in p and 'image' in p['inline_data']['mime_type']), None)
        if inline_part:
            mime_type = inline_part['inline_data']['mime_type']
            image_data = base64.b64decode(inline_part['inline_data']['data'])
        else:
            # If not found, try to find a file URI from fileData and download the image
            # Note: Gemini API returns camelCase keys like 'fileData'
            uri_part = next((p for p in parts if 'fileData' in p and 'image' in p['fileData']['mimeType']), None)
            if uri_part:
                try:
                    mime_type = uri_part['fileData']['mimeType']
                    image_url = uri_part['fileData']['fileUri']
                    # Download the image from the public URL
                    image_response = requests.get(image_url, timeout=60)
                    image_response.raise_for_status()
                    image_data = image_response.content
                except (RequestException, HTTPError) as e:
                    print(f"Failed to download image from URI {uri_part.get('fileData', {}).get('fileUri')}: {e}")
                    image_data = None  # Ensure image_data is None on failure

        db_conn = get_db_connection()
        if not image_data or not mime_type:
            text_response = " ".join(p.get('text', '') for p in parts).strip() or "Sorry, I couldn't generate an image. The model returned an unexpected response."
            bot_text_parts = [{"text": text_response}]
            db_conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)', (chat_id, 'model', json.dumps(bot_text_parts)))
            db_conn.commit()
            db_conn.close()
            return jsonify({'content': text_response})

        # 4. Save image and bot message to DB
        ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'

        chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
        os.makedirs(chat_upload_folder, exist_ok=True)
        filename = f"generated_image_{len(os.listdir(chat_upload_folder))}.{ext}"
        filepath = os.path.join(chat_upload_folder, filename)

        with open(filepath, 'wb') as f:
            f.write(image_data)

        relative_path = os.path.relpath(filepath, UPLOAD_FOLDER)
        file_url = f"/uploads/{relative_path.replace(os.sep, '/')}"

        text_part = " ".join(p.get('text', '') for p in parts if 'text' in p).strip()
        bot_response_text = text_part or f"Here is the generated image for '{prompt}':"

        bot_parts = [
            {"text": bot_response_text},
            {"file_data": {"mime_type": mime_type, "path": filepath}}
        ]
        db_conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)', (chat_id, 'model', json.dumps(bot_parts)))
        db_conn.commit()
        db_conn.close()

        # 5. Return markdown content to the frontend
        response_content = f"{bot_response_text}\n![{prompt}]({file_url})"
        return jsonify({'content': response_content})

    except (HTTPError, ConnectionError, Timeout, RequestException) as e:
        error_message = f"Error from upstream API: {e}"
        print(error_message)
        return jsonify({"error": error_message}), 500
    except Exception as e:
        error_message = f"An error occurred in generate image API: {str(e)}"
        print(error_message)
        return jsonify({"error": error_message}), 500


@web_ui_chat_bp.route('/chat_api', methods=['POST'])
def chat_api():
    """
    Handles direct chat requests from the web UI, with session support.
    """
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        chat_id = request.form.get('chat_id', type=int)
        if not chat_id:
            return jsonify({"error": "chat_id is required"}), 400

        model = request.form.get('model', 'gemini-1.5-flash-latest')
        user_message = request.form.get('message', '')
        attached_files = request.files.getlist('file')
        system_prompt_name = request.form.get('system_prompt_name')
        selected_mcp_tools = request.form.getlist('mcp_tools')

        user_parts = []
        if user_message:
            user_parts.append({"text": user_message})

        if attached_files:
            chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
            os.makedirs(chat_upload_folder, exist_ok=True)
            for attached_file in attached_files:
                filename = secure_filename(attached_file.filename)
                filepath = os.path.join(chat_upload_folder, filename)
                attached_file.save(filepath)
                user_parts.append({
                    "file_data": {"mime_type": attached_file.mimetype, "path": filepath}
                })

        if user_parts:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)',
                (chat_id, 'user', json.dumps(user_parts))
            )
            if user_message:
                message_count = conn.execute('SELECT COUNT(id) FROM messages WHERE chat_id = ? AND role = "user"', (chat_id,)).fetchone()[0]
                if message_count == 1:
                    new_title = (user_message[:47] + '...') if len(user_message) > 50 else user_message
                    conn.execute('UPDATE chats SET title = ? WHERE id = ?', (new_title, chat_id))
            conn.commit()
            conn.close()

        conn = get_db_connection()
        db_messages = conn.execute(
            'SELECT role, parts FROM messages WHERE chat_id = ? ORDER BY id ASC', (chat_id,)
        ).fetchall()
        conn.close()

        gemini_contents = []
        disable_tools = False

        if system_prompt_name and system_prompt_name in utils.system_prompts:
            sp_config = utils.system_prompts[system_prompt_name]
            system_prompt_text = sp_config.get('prompt')

            if system_prompt_text:
                # Inject system prompt as the initial message of the conversation history
                # We use 'user' role for consistency with how Gemini handles system instructions
                gemini_contents.append({
                    'role': 'user',
                    'parts': [{'text': system_prompt_text}]
                })
                utils.log(f"Injected system prompt profile: {system_prompt_name}")

            disable_tools = sp_config.get('disable_tools', False)

        for m in db_messages:
            role = m['role']
            parts = json.loads(m['parts'])
            reconstructed_parts = []
            for part in parts:
                if 'file_data' in part:
                    file_path = part['file_data']['path']
                    if os.path.exists(file_path):
                        with open(file_path, 'rb') as f:
                            file_content = f.read()
                        file_base64 = base64.b64encode(file_content).decode('utf-8')
                        reconstructed_parts.append({
                            "inline_data": {"mime_type": part['file_data']['mime_type'], "data": file_base64}
                        })
                    else:
                        reconstructed_parts.append({"text": f"[File not found: {os.path.basename(file_path)}]"})
                else:
                    reconstructed_parts.append(part)
            gemini_contents.append({'role': role, 'parts': reconstructed_parts})

        full_prompt_text = " ".join(
            [p.get("text", "") for m in gemini_contents for p in m.get("parts", []) if "text" in p]
        )

        def generate():
            GEMINI_STREAMING_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:streamGenerateContent"
            headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
            current_contents = gemini_contents.copy()

            while True:
                token_limit = utils.get_model_input_limit(model, config.API_KEY, config.UPSTREAM_URL)
                safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)
                original_message_count = len(current_contents)
                current_contents = utils.truncate_contents(current_contents, safe_limit)
                if len(current_contents) < original_message_count:
                    utils.log(f"Truncated conversation from {original_message_count} to {len(current_contents)} messages.")

                request_data = {
                    "contents": current_contents,
                    "generationConfig": {"temperature": 0.7, "topP": 1.0, "maxOutputTokens": 2048}
                }

                tools = None
                if selected_mcp_tools:
                    # When tools are selected manually, we force them.
                    # This assumes create_tool_declarations can find tools by their names in text,
                    # and bypasses the 'enabled' check in mcp_handler.
                    tools = mcp_handler.create_tool_declarations(" ".join(selected_mcp_tools))
                    utils.log(f"Using explicitly selected tools: {selected_mcp_tools}")
                else:
                    # Standard tool discovery based on full prompt.
                    tools = mcp_handler.create_tool_declarations(full_prompt_text)

                # Add tools to request if they exist and are not disabled by a system prompt
                # (unless they were manually selected, in which case disable_tools is ignored).
                if tools and (not disable_tools or selected_mcp_tools):
                    request_data["tools"] = tools
                    request_data["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}
                elif disable_tools and not selected_mcp_tools:
                    utils.log(f"Tools omitted due to selected system prompt: {system_prompt_name}")

                try:
                    response = requests.post(
                        GEMINI_STREAMING_URL, headers=headers, json=request_data, stream=True, timeout=300
                    )
                    response.raise_for_status()
                except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                    yield f"ERROR: Error from upstream Gemini API: {e}"
                    return

                buffer, decoder, tool_calls, model_response_parts = "", json.JSONDecoder(), [], []
                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    buffer += chunk
                    while True:
                        start_index = buffer.find('{')
                        if start_index == -1:
                            if len(buffer) > 65536: buffer = buffer[-32768:]
                            break
                        buffer = buffer[start_index:]
                        try:
                            json_data, end_index = decoder.raw_decode(buffer)
                            buffer = buffer[end_index:]
                            if not isinstance(json_data, dict): continue
                            parts = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])
                            if not parts and 'usageMetadata' in json_data: continue
                            model_response_parts.extend(parts)
                            for part in parts:
                                if 'text' in part:
                                    yield part['text']
                                if 'functionCall' in part:
                                    tool_calls.append(part['functionCall'])
                        except json.JSONDecodeError:
                            if len(buffer) > 65536: buffer = buffer[-32768:]
                            break

                    # If the model is silent after a tool call, construct a response from the tool's output
                    # to avoid an empty message and ensure the user sees the result.
                    is_after_tool_call = current_contents and current_contents[-1].get('role') == 'tool'
                    has_text_in_model_response = any('text' in p for p in model_response_parts)

                    if is_after_tool_call and not has_text_in_model_response and not tool_calls:
                        tool_parts_from_history = current_contents[-1].get('parts', [])
                        formatted_tool_outputs = []
                        for tool_part in tool_parts_from_history:
                            func_resp = tool_part.get('functionResponse', {})
                            name = func_resp.get('name', 'unknown_tool')
                            resp_text = func_resp.get('response', {}).get('text', '')
                            if not resp_text:
                                continue
                            try:
                                # Try to parse and pretty-print if it's a JSON string
                                parsed_json = json.loads(json.loads(resp_text))
                                pretty_text = json.dumps(parsed_json, indent=3, default=str)
                                pretty_text = pretty_text.replace('\\n', '\n')
                            except (json.JSONDecodeError, TypeError):
                                pretty_text = resp_text

                            formatted_output = (f'\n<details><summary>Tool Output: `{name}`</summary>\n\n'
                                                            f'```json\n{pretty_text}\n```\n\n</details>\n')
                            formatted_tool_outputs.append(formatted_output)
                            if formatted_tool_outputs:
                                final_text = "".join(formatted_tool_outputs)
                                model_response_parts = [{'text': final_text}]
                                yield final_text

                if model_response_parts:
                    db_conn = get_db_connection()
                    db_conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)',
                                  (chat_id, 'model', json.dumps(model_response_parts)))
                    db_conn.commit()
                    db_conn.close()

                if not tool_calls: break

                utils.log(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({"role": "model", "parts": model_response_parts})

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name = tool_call.get("name")
                    output = mcp_handler.execute_mcp_tool(function_name, tool_call.get("args"))

                    response_payload = {}
                    if output is not None:
                        # Convert any output to a pretty-printed JSON string in the 'text' field.
                        # This is a robust way to present tool output to the model.
                        response_payload = {"text": json.dumps(output, indent=2, default=str)}
                    else:
                        response_payload = {"text": ""}

                    tool_response_parts.append({
                        "functionResponse": {
                            "name": function_name,
                            "response": response_payload
                        }
                    })

                if tool_response_parts:
                    db_conn = get_db_connection()
                    db_conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)',
                                  (chat_id, 'tool', json.dumps(tool_response_parts)))
                    db_conn.commit()
                    db_conn.close()

                current_contents.append({"role": "tool", "parts": tool_response_parts})

        return Response(generate(), mimetype='text/plain')
    except Exception as e:
        print(f"An error occurred in chat API: {str(e)}")
        return jsonify({"error": f"An error occurred in chat API: {str(e)}"}), 500

@web_ui_chat_bp.route('/uploads/<path:filepath>')
def serve_upload(filepath):
    """
    Serves an uploaded file from the UPLOAD_FOLDER.
    """
    # Security: prevent directory traversal attacks
    safe_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filepath))
    if not safe_path.startswith(os.path.abspath(UPLOAD_FOLDER)):
        return "Forbidden", 403

    try:
        return send_from_directory(os.path.dirname(safe_path), os.path.basename(safe_path))
    except FileNotFoundError:
        return "File not found", 404