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
def generate_image_logic(chat_id, model, prompt, generation_type='image'):
    if not config.API_KEY:
        return {"error": "API key not configured."}, 401
    if not all([chat_id, model, prompt]):
        return {"error": "chat_id, model, and prompt are required"}, 400
    try:
        user_parts = [{"text": prompt}]
        utils.add_message_to_db(chat_id, 'user', user_parts)
        media_type = 'video' if generation_type == 'veo' else 'image'
        
        # Detect if using Imagen model
        is_imagen = 'imagen' in model.lower()
        
        MEDIA_GEN_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:generateContent"
        headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
        
        # Build request data with proper configuration for image/video generation
        request_data = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        
        # Configure based on model type
        if media_type == 'image':
            if is_imagen:
                # Imagen models use simpler configuration
                request_data["generationConfig"] = {
                    "temperature": 1.0,
                }
            else:
                # Gemini models need responseModalities for image generation
                request_data["generationConfig"] = {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "temperature": 1.0,
                }
        elif media_type == 'video':
            # For video generation (Veo), use appropriate configuration
            request_data["generationConfig"] = {
                "temperature": 1.0,
            }
        response = utils.make_request_with_retry(
            url=MEDIA_GEN_URL,
            headers=headers,
            json_data=request_data,
            stream=False,
            timeout=600
        )
        response_data = response.json()
        parts = response_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])
        media_data = None
        mime_type = None
        inline_part = next((p for p in parts if 'inline_data' in p and media_type in p['inline_data']['mime_type']), None)
        if inline_part:
            mime_type = inline_part['inline_data']['mime_type']
            media_data = base64.b64decode(inline_part['inline_data']['data'])
        else:
            uri_part = next((p for p in parts if 'fileData' in p and media_type in p['fileData']['mimeType']), None)
            if uri_part:
                try:
                    mime_type = uri_part['fileData']['mimeType']
                    media_url = uri_part['fileData']['fileUri']
                    media_response = requests.get(media_url, timeout=120)
                    media_response.raise_for_status()
                    media_data = media_response.content
                except (RequestException, HTTPError) as e:
                    logging.log(f"Failed to download media from URI {uri_part.get('fileData', {}).get('fileUri')}: {e}")
                    media_data = None
        if not media_data or not mime_type:
            text_response = " ".join(p.get('text', '') for p in parts).strip() or f"Sorry, I couldn't generate a {media_type}. The model returned an unexpected response."
            bot_text_parts = [{"text": text_response}]
            bot_message_id = utils.add_message_to_db(chat_id, 'model', bot_text_parts)
            return {'content': text_response, 'message_id': bot_message_id}, 200
        ext = mime_type.split('/')[-1] if '/' in mime_type else ('mp4' if media_type == 'video' else 'png')
        chat_upload_folder = os.path.join(UPLOAD_FOLDER, str(chat_id))
        os.makedirs(chat_upload_folder, exist_ok=True)
        filename = f"generated_{media_type}_{len(os.listdir(chat_upload_folder))}.{ext}"
        filepath = os.path.join(chat_upload_folder, filename)
        with open(filepath, 'wb') as f:
            f.write(media_data)
        relative_path = os.path.relpath(filepath, UPLOAD_FOLDER)
        file_url = f"/uploads/{relative_path.replace(os.sep, '/')}"
        text_part = " ".join(p.get('text', '') for p in parts if 'text' in p).strip()
        bot_response_text = text_part or f"Here is the generated {media_type} for '{prompt}':"
        bot_parts = [
            {"text": bot_response_text},
            {"file_data": {"mime_type": mime_type, "path": filepath}}
        ]
        bot_message_id = utils.add_message_to_db(chat_id, 'model', bot_parts)
        if media_type == 'video':
            response_content = f"{bot_response_text}\n<video controls src='{file_url}' style='max-width: 100%; border-radius: 0.5rem; margin-top: 0.5rem;'></video>"
        else:
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
                        else:
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