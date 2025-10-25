"""
Flask routes for the web chat UI, including the main page and direct chat API.
Compatible with both Flask and Quart.
"""
import base64
import json
import shutil
import requests
import os
import mimetypes
from flask import Blueprint, request, jsonify, Response, send_from_directory
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
from werkzeug.utils import secure_filename
from app.config import config
from app.utils.flask import mcp_handler
from app.utils.core import tools as utils
from app.utils.core import tool_config_utils
from app.utils.core import file_processing_utils
from app.db import get_db_connection, UPLOAD_FOLDER
from app.utils.flask.optimization import record_token_usage # Import token usage tracking


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

@web_ui_chat_bp.route('/api/chats/<int:chat_id>/title', methods=['PUT'])
def update_chat_title(chat_id):
    data = request.json
    new_title = data.get('title')
    if not new_title:
        return jsonify({'error': 'Title is required'}), 400

    try:
        conn = get_db_connection()
        conn.execute('UPDATE chats SET title = ? WHERE id = ?', (new_title, chat_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'new_title': new_title})
    except Exception as e:
        utils.log(f"Error updating title for chat {chat_id}: {e}")
        return jsonify({'error': str(e)}), 500

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
        utils.log(f"Error deleting files for chat {chat_id}: {e}")

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
    return jsonify(formatted_messages)


@web_ui_chat_bp.route('/api/messages/<int:message_id>', methods=['DELETE'])
def delete_message(message_id):
    """Deletes a single message from the database."""
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM messages WHERE id = ?', (message_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        utils.log(f"Error deleting message {message_id}: {e}")
        return jsonify({'error': str(e)}), 500


@web_ui_chat_bp.route('/api/generate_image', methods=['POST'])
def generate_image_api():
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        form = request.form
        chat_id = form.get('chat_id', type=int)
        model = form.get('model', 'gemini-1.5-pro-latest')
        prompt = form.get('prompt', '')

        if not all([chat_id, model, prompt]):
            return jsonify({"error": "chat_id, model, and prompt are required"}), 400

        # 1. Save user message to DB
        user_parts = [{"text": prompt}]
        utils.add_message_to_db(chat_id, 'user', user_parts)

        # 2. Call the image generation model via non-streaming API
        IMAGE_GEN_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:generateContent"
        headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
        request_data = {
            "contents": [{"parts": [{"text": f"Generate an image of: {prompt}"}]}],
        }

        response = utils.make_request_with_retry(
            url=IMAGE_GEN_URL,
            headers=headers,
            json_data=request_data,
            stream=False,
            timeout=300
        )
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
                    utils.log(f"Failed to download image from URI {uri_part.get('fileData', {}).get('fileUri')}: {e}")
                    image_data = None  # Ensure image_data is None on failure

        if not image_data or not mime_type:
            text_response = " ".join(p.get('text', '') for p in parts).strip() or "Sorry, I couldn't generate an image. The model returned an unexpected response."
            bot_text_parts = [{"text": text_response}]
            bot_message_id = utils.add_message_to_db(chat_id, 'model', bot_text_parts)
            return jsonify({'content': text_response, 'message_id': bot_message_id})

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
        bot_message_id = utils.add_message_to_db(chat_id, 'model', bot_parts)

        # 5. Return markdown content to the frontend
        response_content = f"{bot_response_text}\n![{prompt}]({file_url})"
        return jsonify({'content': response_content, 'message_id': bot_message_id})

    except (HTTPError, ConnectionError, Timeout, RequestException) as e:
        error_message = f"Error from upstream API: {e}"
        utils.log(error_message)
        return jsonify({"error": error_message}), 500
    except Exception as e:
        error_message = f"An error occurred in generate image API: {str(e)}"
        utils.log(error_message)
        return jsonify({"error": error_message}), 500


@web_ui_chat_bp.route('/chat_api', methods=['POST'])
def chat_api():
    """
    Handles direct chat requests from the web UI, with session support.
    """
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        form = request.form
        files = request.files
        
        chat_id = form.get('chat_id', type=int)
        if not chat_id:
            return jsonify({"error": "chat_id is required"}), 400

        model = form.get('model', 'gemini-flash-latest')
        user_message = form.get('message', '')
        attached_files = files.getlist('file')
        system_prompt_name = form.get('system_prompt_name')
        selected_mcp_tools = form.getlist('mcp_tools')

        utils.log(f"Incoming Web UI Chat Request (Chat ID: {chat_id}): "
                  f"Model='{model}', User='{user_message[:50]}...', "
                  f"Files={len(attached_files)}, SystemPrompt='{system_prompt_name}', "
                  f"Tools='{selected_mcp_tools}'")

        # --- Prompt Engineering & Tool Control ---
        # Fetch history to build full context for prompt engineering
        conn = get_db_connection()
        db_messages_for_prompt = conn.execute(
            'SELECT parts FROM messages WHERE chat_id = ? ORDER BY id ASC', (chat_id,)
        ).fetchall()
        conn.close()

        history_text = " ".join(
            p.get("text", "")
            for m in db_messages_for_prompt
            for p in json.loads(m['parts'])
            if p.get("text")
        )
        full_prompt_for_override_check = f"{history_text} {user_message}".strip()

        # Apply Prompt Engineering & Tool Control Overrides
        override_config = tool_config_utils.get_prompt_override_config(full_prompt_for_override_check)

        active_overrides = override_config['active_overrides']
        disable_mcp_tools_override = override_config['disable_mcp_tools_by_profile']
        enable_native_tools_override = override_config['enable_native_tools_by_profile']
        profile_selected_mcp_tools = override_config['profile_selected_mcp_tools']

        if active_overrides and user_message:
            for find, replace in active_overrides.items():
                if find in user_message:
                    user_message = user_message.replace(find, replace)
        # --- End Prompt Engineering ---

        user_parts = []
        code_project_root = None # Path for project context if 'project_path=' was used
        code_tools_requested = False # Flag to force built-in tool enablement

        if user_message:
            # Process message for local file paths (e.g., code_path=, image_path=)
            processed_result = user_message
            if not disable_mcp_tools_override:
                processed_result = file_processing_utils.process_message_for_paths(user_message)

            if isinstance(processed_result, str):
                # No paths were found, treat as a simple text message
                if processed_result:
                    user_parts.append({"text": processed_result})
            elif isinstance(processed_result, tuple):
                # Paths were found and processed into parts. (list[parts], project_root_path_or_None)
                processed_content, project_path_found = processed_result

                if project_path_found:
                    code_project_root = project_path_found
                    code_tools_requested = True

                chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
                os.makedirs(chat_upload_folder, exist_ok=True)

                for part in processed_content:
                    part_type = part.get("type")
                    if part_type == "text" and part.get("text"):
                        user_parts.append({"text": part.get("text")})
                    elif part_type in ("image_url", "inline_data"):
                        # This part contains base64 encoded data that needs to be saved to a file
                        try:
                            if part_type == "image_url":
                                data_uri = part.get("image_url", {}).get("url", "")
                                header, encoded = data_uri.split(",", 1)
                                mime_type = header.split(":")[1].split(";")[0]
                                file_bytes = base64.b64decode(encoded)
                            else:  # inline_data
                                source = part.get("source", {})
                                mime_type = source.get("media_type")
                                file_bytes = base64.b64decode(source.get("data"))

                            if mime_type and file_bytes:
                                ext = mimetypes.guess_extension(mime_type) or '.bin'
                                filename = f"path_import_{os.urandom(8).hex()}{ext}"
                                filepath = os.path.join(chat_upload_folder, filename)

                                with open(filepath, 'wb') as f:
                                    f.write(file_bytes)

                                user_parts.append({
                                    "file_data": {"mime_type": mime_type, "path": filepath}
                                })
                                utils.log(f"Saved path-imported file to {filepath}")
                        except Exception as e:
                            utils.log(f"Error processing path-imported file part: {e}")
                            user_parts.append({"text": f"[Error processing file part: {str(e)}]"})

        if attached_files:
            chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
            os.makedirs(chat_upload_folder, exist_ok=True)
            MAX_FILE_SIZE_MB = 10
            MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

            for attached_file in attached_files:
                # Check file size before saving and processing
                start_pos = attached_file.tell()
                attached_file.seek(0, os.SEEK_END)
                file_size = attached_file.tell()
                attached_file.seek(start_pos)

                if file_size > MAX_FILE_SIZE:
                    user_parts.append({"text": f"[File '{secure_filename(attached_file.filename)}' was skipped because it exceeds the {MAX_FILE_SIZE_MB}MB size limit.]"})
                    continue

                filename = secure_filename(attached_file.filename)
                filepath = os.path.join(chat_upload_folder, filename)
                attached_file.save(filepath)
                user_parts.append({
                    "file_data": {"mime_type": attached_file.mimetype, "path": filepath}
                })

        if user_parts:
            utils.add_message_to_db(chat_id, 'user', user_parts)
            # Use the text from the processed parts to generate the title
            user_text_for_title = " ".join([p['text'] for p in user_parts if 'text' in p]).strip()

            if user_text_for_title:
                conn = get_db_connection()
                message_count = conn.execute('SELECT COUNT(id) FROM messages WHERE chat_id = ? AND role = "user"', (chat_id,)).fetchone()[0]
                if message_count == 1:
                    new_title = (user_text_for_title[:47] + '...') if len(user_text_for_title) > 50 else user_text_for_title
                    conn.execute('UPDATE chats SET title = ? WHERE id = ?', (new_title, chat_id))
                conn.commit()
                conn.close()

        conn = get_db_connection()
        db_messages = conn.execute(
            'SELECT role, parts FROM messages WHERE chat_id = ? ORDER BY id ASC', (chat_id,)
        ).fetchall()
        conn.close()

        gemini_contents = []
        # --- Tool Configuration Logic ---
        # Start with settings from prompt override profile
        disable_mcp_tools = disable_mcp_tools_override
        enable_native_tools = enable_native_tools_override
        # `profile_selected_mcp_tools` is already set from prompt override config

        # System prompt settings take precedence if a system prompt is selected
        if system_prompt_name and system_prompt_name in utils.system_prompts:
            sp_config = utils.system_prompts[system_prompt_name]
            system_prompt_text = sp_config.get('prompt')

            if system_prompt_text:
                # Inject system prompt as the initial message of the conversation history
                gemini_contents.append({
                    'role': 'user',
                    'parts': [{'text': system_prompt_text}]
                })
                utils.log(f"Injected system prompt profile: {system_prompt_name}")

            # Check if tools are disabled by the system prompt. This takes precedence.
            if sp_config.get('disable_tools', False):
                utils.log(f"MCP Tools disabled by system prompt '{system_prompt_name}'.")
                disable_mcp_tools = True
                profile_selected_mcp_tools = [] # Clear any tools selected by prompt override
            # Only if tools are NOT disabled by this profile, check for specific tool selection.
            elif sp_config.get('selected_mcp_tools'):
                utils.log(f"MCP Tools explicitly selected by system prompt '{system_prompt_name}': {sp_config['selected_mcp_tools']}")
                profile_selected_mcp_tools = sp_config['selected_mcp_tools']
                disable_mcp_tools = False # Make sure tools are enabled

            # For native tools, either a system prompt or prompt override can enable them.
            if sp_config.get('enable_native_tools', False):
                enable_native_tools = True
                utils.log(f"Native Google tools enabled by system prompt: {system_prompt_name}")

        # Global setting to disable all MCP tools takes highest precedence
        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            disable_mcp_tools = True
            profile_selected_mcp_tools = [] # Clear any profile-selected tools

        for m in db_messages:
            role = m['role']
            reconstructed_parts = utils.prepare_message_parts_for_gemini(m['parts'])
            gemini_contents.append({'role': role, 'parts': reconstructed_parts})

        def generate():
            headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
            current_contents = gemini_contents.copy()
            final_tool_call_response = {} # Initialize for token usage tracking

            while True:
                token_limit = utils.get_model_input_limit(model, config.API_KEY, config.UPSTREAM_URL)
                safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)
                original_message_count = len(current_contents)
                
                current_query = ""
                if current_contents:
                    # Get the last user message
                    for msg in reversed(current_contents):
                        if msg.get('role') == 'user':
                            parts = msg.get('parts', [])
                            for part in parts:
                                if 'text' in part:
                                    current_query = part['text']
                                    break
                            if current_query:
                                break
                
                current_contents = utils.truncate_contents(current_contents, safe_limit, current_query=current_query)
                if len(current_contents) < original_message_count:
                    utils.log(f"Truncated conversation from {original_message_count} to {len(current_contents)} messages.")

                request_data = {
                    "contents": current_contents,
                    "generationConfig": {"temperature": 0.7, "topP": 1.0, "maxOutputTokens": 2048}
                }

                # --- Tool Configuration ---
                final_tools = []
                mcp_declarations_to_use = None

                # Built-in tools list (only function names)
                builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())

                # Priority for MCP tools:
                if code_tools_requested and not disable_mcp_tools and not mcp_handler.disable_all_mcp_tools:
                    # 1. If code_path= was used, force-enable built-in tools only.
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(builtin_tool_names)
                    utils.log(f"Code context requested via code_path=. Forcing use of built-in tools: {builtin_tool_names}")
                elif selected_mcp_tools:
                    # 2. User-selected tools from chat UI (highest priority)
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(selected_mcp_tools)
                    utils.log(f"Using explicitly selected tools from UI (overriding profiles): {selected_mcp_tools}")
                elif profile_selected_mcp_tools:
                    # 3. Profile-defined selected tools (system prompt or prompt override)
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(profile_selected_mcp_tools)
                    utils.log(f"Using MCP tools defined by profile: {profile_selected_mcp_tools}")
                elif not disable_mcp_tools:  # Only use context-aware if not explicitly disabled and no specific tools selected
                    # 4. Context-aware tools (default)
                    prompt_text_for_tools = " ".join(
                        [p.get("text", "") for m in current_contents for p in m.get("parts", []) if "text" in p]
                    )
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations(prompt_text_for_tools)
                    utils.log(f"Using context-aware tool selection based on prompt.")
                else:
                    utils.log(f"MCP Tools explicitly disabled by profile or global setting.")

                if mcp_declarations_to_use:
                    final_tools.extend(mcp_declarations_to_use)

                if enable_native_tools:
                    final_tools.append({"google_search": {}})
                    final_tools.append({"url_context": {}})

                if final_tools:
                    request_data["tools"] = final_tools
                    # Add tool_config only if there are function-callable tools
                    if mcp_declarations_to_use:
                        request_data["tool_config"] = {
                            "function_calling_config": {
                                "mode": "AUTO"
                            }
                        }

                utils.debug(f"Outgoing Gemini Request (Model: {model}, Tools: {bool(final_tools)}): {utils.pretty_json(request_data)}")

                tool_calls, model_response_parts = [], []

                if enable_native_tools:
                    # Non-streaming path to support inline citations for native tools
                    GEMINI_GENERATE_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:generateContent"
                    try:
                        response = utils.make_request_with_retry(
                            url=GEMINI_GENERATE_URL,
                            headers=headers,
                            json_data=request_data,
                            stream=False,
                            timeout=300
                        )
                        response_data = response.json()

                        utils.debug(f"Incoming Gemini Non-Streaming Response: {utils.pretty_json(response_data)}")

                        final_tool_call_response = response_data

                        if not response_data.get('candidates'):
                            err_msg = "The model did not return a response. This could be due to a safety filter."
                            model_response_parts = [{'text': err_msg}]
                            yield err_msg
                        else:
                            candidate = response_data.get('candidates', [{}])[0]
                            model_response_parts = candidate.get('content', {}).get('parts', [])
                            tool_calls = [p['functionCall'] for p in model_response_parts if 'functionCall' in p]
                            full_text = " ".join(p.get('text', '') for p in model_response_parts if 'text' in p)

                            if 'groundingMetadata' in candidate and full_text:
                                try:
                                    text = full_text
                                    metadata = candidate['groundingMetadata']
                                    supports = metadata.get('groundingSupports', [])
                                    chunks = metadata.get('groundingChunks', [])
                                    sorted_supports = sorted(supports, key=lambda s: s.get('segment', {}).get('endIndex', 0), reverse=True)

                                    for support in sorted_supports:
                                        end_index = support.get('segment', {}).get('endIndex')
                                        if end_index is not None and 'groundingChunkIndices' in support:
                                            links = [f"[{chunks[i].get('web', {}).get('title') or i + 1}]({chunks[i].get('web', {}).get('uri')})"
                                                     for i in support['groundingChunkIndices'] if i < len(chunks) and chunks[i].get('web', {}).get('uri')]
                                            if links:
                                                text = text[:end_index] + " " + ", ".join(links) + text[end_index:]
                                    full_text = text
                                    new_parts = [p for p in model_response_parts if 'text' not in p]
                                    new_parts.insert(0, {'text': full_text})
                                    model_response_parts = new_parts
                                except Exception as e:
                                    utils.log(f"Error processing citations: {e}")
                            if full_text:
                                yield full_text
                    except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                        yield f"ERROR: Error from upstream Gemini API: {e}"
                        return
                else:
                    # Original streaming path
                    GEMINI_STREAMING_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:streamGenerateContent"
                    try:
                        response = utils.make_request_with_retry(
                            url=GEMINI_STREAMING_URL,
                            headers=headers,
                            json_data=request_data,
                            stream=True,
                            timeout=300
                        )
                    except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                        yield f"ERROR: Error from upstream Gemini API: {e}"
                        return

                    buffer, decoder = "", json.JSONDecoder()
                    text_buffer = ""  # Buffer for partial text to avoid breaking words
                    
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

                                if 'error' in json_data:
                                    error_message = "ERROR: Error from upstream Gemini API: " + json.dumps(json_data['error'])
                                    utils.log(error_message)
                                    yield error_message
                                    return

                                parts = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])

                                if 'usageMetadata' in json_data:
                                    final_tool_call_response = json_data
                                    if not parts: continue # Skip chunk if it contains only metadata

                                model_response_parts.extend(parts)
                                for part in parts:
                                    if 'text' in part:
                                        text_buffer += part['text']
                                        # Yield complete segments only to prevent word splitting
                                        # Look for natural boundaries: spaces, newlines, punctuation
                                        if any(c in text_buffer for c in [' ', '\n', '\t', '.', ',', '!', '?', ';', ':', ')', ']', '}', '>', '"', "'"]):
                                            # Find the last natural boundary
                                            last_boundary = -1
                                            for boundary_char in ['\n', ' ', '\t', '.', ',', '!', '?', ';', ':', ')', ']', '}', '>']:
                                                pos = text_buffer.rfind(boundary_char)
                                                if pos > last_boundary:
                                                    last_boundary = pos
                                            
                                            if last_boundary > 0:
                                                complete_text = text_buffer[:last_boundary + 1]
                                                text_buffer = text_buffer[last_boundary + 1:]
                                                yield complete_text
                                    if 'functionCall' in part: tool_calls.append(part['functionCall'])
                            except json.JSONDecodeError:
                                if len(buffer) > 65536: buffer = buffer[-32768:]
                                break
                    
                    # Yield any remaining text in buffer
                    if text_buffer:
                        yield text_buffer

                # Handle silent model response after a tool call
                is_after_tool_call = current_contents and current_contents[-1].get('role') == 'tool'
                has_text_in_model_response = any('text' in p for p in model_response_parts)
                if is_after_tool_call and not has_text_in_model_response and not tool_calls:
                    tool_parts_from_history = current_contents[-1].get('parts', [])
                    final_text = utils.format_tool_output_for_display(tool_parts_from_history)
                    if final_text:
                        model_response_parts = [{'text': final_text}]
                        yield final_text

                if model_response_parts:
                    bot_message_id = utils.add_message_to_db(chat_id, 'model', model_response_parts)
                    utils.debug(f"Model response saved to DB (Chat ID: {chat_id}). Parts: {utils.pretty_json(model_response_parts)}")
                    # Yield a special event with the message ID so the frontend can add a delete button
                    yield f'__LLM_EVENT__{json.dumps({"type": "message_id", "id": bot_message_id})}'

                # Record token usage after a response turn is complete
                if not tool_calls:
                    # The last chunk usually contains usage metadata in Gemini API responses
                    api_key_header = headers.get('X-goog-api-key') or config.API_KEY
                    usage_metadata = final_tool_call_response.get('usageMetadata', {})
                    input_tokens = usage_metadata.get('promptTokenCount', 0)
                    output_tokens = usage_metadata.get('candidatesTokenCount', 0)
                    record_token_usage(api_key_header, model, input_tokens, output_tokens)

                if not tool_calls: break

                utils.debug(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({"role": "model", "parts": model_response_parts})

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name = tool_call.get("name")
                    utils.debug(f"Executing tool '{function_name}' with args: {utils.pretty_json(tool_call.get('args'))}")
                    # Pass the project root for built-in tools executed in this sync thread.
                    output = mcp_handler.execute_mcp_tool(function_name, tool_call.get("args"), code_project_root)
                    utils.log(f"Tool '{function_name}' execution completed. Output length: {len(str(output))}")

                    response_payload = {}
                    if output is not None:
                        try:
                            # If tool returns a JSON string, parse it into a JSON object for the API
                            response_payload = json.loads(output)
                        except (json.JSONDecodeError, TypeError):
                            # Otherwise, treat it as plain text and wrap it in a standard 'content' object
                            response_payload = {"content": str(output)}
                    else:
                        response_payload = {} # If there's no output, provide an empty object

                    tool_response_parts.append({
                        "functionResponse": {
                            "name": function_name,
                            "response": response_payload
                        }
                    })

                if tool_response_parts:
                    utils.add_message_to_db(chat_id, 'tool', tool_response_parts)
                    utils.debug(f"Tool response saved to DB (Chat ID: {chat_id}). Response Parts: {utils.pretty_json(tool_response_parts)}")

                current_contents.append({"role": "tool", "parts": tool_response_parts})

        return Response(generate(), mimetype='text/event-stream'
                        )
    except Exception as e:
        utils.log(f"An error occurred in chat API: {str(e)}")
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