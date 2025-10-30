"""
Shared business logic for web UI chat controllers (Flask & Quart).
"""
import base64
import json
import os
import mimetypes
import requests
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
from werkzeug.utils import secure_filename

from app.config import config
from app.db import get_db_connection, UPLOAD_FOLDER
from app.utils.core import chat_db_utils, file_processing_utils, logging, mcp_handler
from app.utils.core import tool_config_utils
from app.utils.core import tools as utils


def generate_image_logic(chat_id, model, prompt):
    """Handles the logic for generating an image."""
    if not config.API_KEY:
        return {"error": "API key not configured."}, 401

    if not all([chat_id, model, prompt]):
        return {"error": "chat_id, model, and prompt are required"}, 400

    try:
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
                    logging.log(f"Failed to download image from URI {uri_part.get('fileData', {}).get('fileUri')}: {e}")
                    image_data = None  # Ensure image_data is None on failure

        if not image_data or not mime_type:
            text_response = " ".join(p.get('text', '') for p in parts).strip() or "Sorry, I couldn't generate an image. The model returned an unexpected response."
            bot_text_parts = [{"text": text_response}]
            bot_message_id = utils.add_message_to_db(chat_id, 'model', bot_text_parts)
            return {'content': text_response, 'message_id': bot_message_id}, 200

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
        return {'content': response_content, 'message_id': bot_message_id}, 200

    except (HTTPError, ConnectionError, Timeout, RequestException) as e:
        error_message = f"Error from upstream API: {e}"
        logging.log(error_message)
        return {"error": error_message}, 500
    except Exception as e:
        error_message = f"An error occurred in generate image API: {str(e)}"
        logging.log(error_message)
        return {"error": error_message}, 500


def prepare_chat_data(form, files):
    """Prepares all data needed for a chat API request, handling form data, files, and prompt engineering."""
    chat_id = form.get('chat_id', type=int)
    if not chat_id:
        return {"error": "chat_id is required"}, 400, None

    model = form.get('model', 'gemini-flash-latest')
    user_message = form.get('message', '')
    attached_files = files.getlist('file')
    system_prompt_name = form.get('system_prompt_name')
    selected_mcp_tools = form.getlist('mcp_tools')

    logging.log(f"Incoming Web UI Chat Request (Chat ID: {chat_id}): "
                f"Model='{model}', User='{user_message[:50]}...', "
                f"Files={len(attached_files)}, SystemPrompt='{system_prompt_name}', "
                f"Tools='{selected_mcp_tools}'")

    # --- Prompt Engineering & Tool Control ---
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

    override_config = tool_config_utils.get_prompt_override_config(full_prompt_for_override_check)
    active_overrides = override_config['active_overrides']
    disable_mcp_tools_override = override_config['disable_mcp_tools_by_profile']
    enable_native_tools_override = override_config['enable_native_tools_by_profile']
    profile_selected_mcp_tools = override_config['profile_selected_mcp_tools']

    if active_overrides and user_message:
        for find, replace in active_overrides.items():
            if find in user_message:
                user_message = user_message.replace(find, replace)

    # --- Process User Input ---
    user_parts = []
    project_context_root = None
    project_context_tools_requested = False
    system_context_text = None

    if user_message:
        processed_content, project_path_found, system_context_text = file_processing_utils.process_message_for_paths(
            user_message, set()
        )

        if isinstance(processed_content, str):
            if processed_content:
                user_parts.append({"text": processed_content})
        elif isinstance(processed_content, list):
            if project_path_found:
                project_context_root = project_path_found
                project_context_tools_requested = True

            chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
            os.makedirs(chat_upload_folder, exist_ok=True)

            for part in processed_content:
                if part.get("type") == "text" and part.get("text"):
                    user_parts.append({"text": part.get("text")})
                elif part.get("type") in ("image_url", "inline_data"):
                    try:
                        if part.get("type") == "image_url":
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
                            user_parts.append({"file_data": {"mime_type": mime_type, "path": filepath}})
                    except Exception as e:
                        logging.log(f"Error processing path-imported file part: {e}")

    if attached_files:
        chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
        os.makedirs(chat_upload_folder, exist_ok=True)
        MAX_FILE_SIZE_MB = 10
        MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024
        for f in attached_files:
            start_pos = f.tell()
            f.seek(0, os.SEEK_END)
            if f.tell() > MAX_FILE_SIZE:
                user_parts.append({"text": f"[File '{secure_filename(f.filename)}' skipped: exceeds {MAX_FILE_SIZE_MB}MB limit.]"})
                f.seek(start_pos)
                continue
            f.seek(start_pos)
            filename = secure_filename(f.filename)
            filepath = os.path.join(chat_upload_folder, filename)
            f.save(filepath)
            user_parts.append({"file_data": {"mime_type": f.mimetype, "path": filepath}})

    if user_parts:
        utils.add_message_to_db(chat_id, 'user', user_parts)
        user_text_for_title = " ".join([p['text'] for p in user_parts if 'text' in p]).strip()
        if user_text_for_title:
            conn = get_db_connection()
            msg_count = conn.execute('SELECT COUNT(id) FROM messages WHERE chat_id = ? AND role = "user"', (chat_id,)).fetchone()[0]
            if msg_count == 1:
                new_title = (user_text_for_title[:47] + '...') if len(user_text_for_title) > 50 else user_text_for_title
                conn.execute('UPDATE chats SET title = ? WHERE id = ?', (new_title, chat_id))
            conn.commit()
            conn.close()

    # --- Build Gemini Contents ---
    conn = get_db_connection()
    db_messages = conn.execute('SELECT role, parts FROM messages WHERE chat_id = ? ORDER BY id ASC', (chat_id,)).fetchall()
    conn.close()

    gemini_contents = []
    disable_mcp_tools = disable_mcp_tools_override
    enable_native_tools = enable_native_tools_override

    system_prompt_to_inject = None
    if system_prompt_name and system_prompt_name in utils.system_prompts:
        sp_config = utils.system_prompts[system_prompt_name]
        if sp_config.get('prompt'):
            system_prompt_to_inject = sp_config.get('prompt')
        if sp_config.get('disable_tools', False):
            disable_mcp_tools = True
            profile_selected_mcp_tools = []
        elif sp_config.get('selected_mcp_tools'):
            profile_selected_mcp_tools = sp_config['selected_mcp_tools']
            disable_mcp_tools = False
        if sp_config.get('enable_native_tools', False):
            enable_native_tools = True

    if project_context_root and system_context_text:
        system_prompt_to_inject = system_context_text

    if system_prompt_to_inject:
        gemini_contents.append({'role': 'user', 'parts': [{'text': system_prompt_to_inject}]})

    if mcp_handler.disable_all_mcp_tools:
        disable_mcp_tools = True
        profile_selected_mcp_tools = []

    for m in db_messages:
        role = m['role']
        reconstructed_parts = utils.prepare_message_parts_for_gemini(m['parts'])
        if gemini_contents and gemini_contents[-1]['role'] == role:
            gemini_contents[-1]['parts'].extend(reconstructed_parts)
        else:
            gemini_contents.append({'role': role, 'parts': reconstructed_parts})

    if gemini_contents and gemini_contents[0]['role'] == 'model':
        gemini_contents.insert(0, {'role': 'user', 'parts': [{'text': '----'}]})

    data = {
        'chat_id': chat_id, 'model': model, 'gemini_contents': gemini_contents,
        'disable_mcp_tools': disable_mcp_tools, 'enable_native_tools': enable_native_tools,
        'project_context_root': project_context_root, 'project_context_tools_requested': project_context_tools_requested,
        'selected_mcp_tools': selected_mcp_tools, 'profile_selected_mcp_tools': profile_selected_mcp_tools
    }
    return data, 200, None
