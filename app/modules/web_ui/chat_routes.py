import httpx
import asyncio
import fnmatch
import json
import os
import time
from flask import Blueprint, request, jsonify, Response, send_from_directory
from httpx import HTTPStatusError, RequestError
from app.config import config
from app.utils.core import mcp_handler, tools as utils, logging, chat_db_utils
from app.db import UPLOAD_FOLDER
from app.utils.flask.optimization import record_token_usage
from app.utils.core import chat_web_logic
from app.utils.core.ai_provider_manager import ai_provider_manager

web_ui_chat_bp = Blueprint('web_ui_chat', __name__)
@web_ui_chat_bp.route('/api/chats', methods=['GET'])
def get_chats():
    chats = chat_db_utils.get_all_chats()
    return jsonify(chats)
@web_ui_chat_bp.route('/api/chats', methods=['POST'])
def create_chat():
    new_chat = chat_db_utils.create_new_chat()
    return jsonify(new_chat), 201
@web_ui_chat_bp.route('/api/chats/<int:chat_id>/title', methods=['PUT'])
def update_chat_title(chat_id):
    data = request.json
    new_title = data.get('title')
    if not new_title:
        return jsonify({'error': 'Title is required'}), 400
    try:
        chat_db_utils.update_chat_title_in_db(chat_id, new_title)
        return jsonify({'success': True, 'new_title': new_title})
    except Exception as e:
        logging.log(f"Error updating title for chat {chat_id}: {e}")
        return jsonify({'error': str(e)}), 500
@web_ui_chat_bp.route('/api/chats/<int:chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    chat_db_utils.delete_chat_and_files(chat_id)
    return jsonify({'success': True}), 200
@web_ui_chat_bp.route('/api/chats/<int:chat_id>/messages', methods=['GET'])
def get_chat_messages(chat_id):
    formatted_messages = chat_db_utils.get_messages_for_chat(chat_id)
    return jsonify(formatted_messages)
@web_ui_chat_bp.route('/api/messages/<int:message_id>', methods=['DELETE'])
def delete_message(message_id):
    try:
        chat_db_utils.delete_message_from_db(message_id)
        return jsonify({'success': True}), 200
    except Exception as e:
        logging.log(f"Error deleting message {message_id}: {e}")
        return jsonify({'error': str(e)}), 500

@web_ui_chat_bp.route('/api/models', methods=['GET'])
async def list_models():
    import fnmatch
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        # if utils.cached_models_response:
        #     return jsonify(utils.cached_models_response)

        openai_models_list = []

        # 1. Fetch Gemini Models
        try:
            params = {"key": config.API_KEY}
            GEMINI_MODELS_URL = f"{config.UPSTREAM_URL}/v1beta/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(GEMINI_MODELS_URL, params=params)
                response.raise_for_status()
                gemini_models_data = response.json()

                for model in gemini_models_data.get("models", []):
                    if "generateContent" in model.get("supportedGenerationMethods", []):
                        openai_models_list.append({
                            "id": model["name"].split("/")[-1], "object": "model",
                            "created": 1677649553, "owned_by": "google", "permission": []
                        })
        except Exception as e:
            utils.log(f"Error fetching Gemini models: {e}")

        # 2. Fetch OpenAI Models from ALL configured providers
        providers = ai_provider_manager.get_all_providers_data().get('providers', {}).values()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for provider in providers:
                if provider.get('api_key') and provider.get('base_url'):
                    try:
                        OPENAI_MODELS_URL = f"{provider['base_url']}/models"
                        headers = {"Authorization": f"Bearer {provider['api_key']}"}
                        response = await client.get(OPENAI_MODELS_URL, headers=headers)
                        if response.status_code == 200:
                            openai_models_data = response.json()
                            for model in openai_models_data.get("data", []):
                                model_id = model.get("id")
                                openai_models_list.append({
                                    "id": model_id, "object": "model",
                                    "created": model.get("created", 1677649553),
                                    "owned_by": model.get("owned_by", "openai-compatible"),
                                    "permission": []
                                })
                                # Register mapping
                                ai_provider_manager.register_model(model_id, provider.get('id'))
                        else:
                            utils.log(f"Error fetching OpenAI models from {provider.get('name')}: Status {response.status_code}")
                    except Exception as e:
                        utils.log(f"Error fetching OpenAI models from {provider.get('name')}: {e}")

        # Deduplicate
        seen_ids = set()
        unique_models_list = []
        for m in openai_models_list:
            if m['id'] not in seen_ids:
                unique_models_list.append(m)
                seen_ids.add(m['id'])
        openai_models_list = unique_models_list

        # Save mappings to disk
        ai_provider_manager.save_providers()

        if config.ALLOWED_MODELS and '*' not in config.ALLOWED_MODELS:
            openai_models_list = [
                m for m in openai_models_list
                if any(fnmatch.fnmatch(m['id'], pattern) for pattern in config.ALLOWED_MODELS)
            ]

        if config.IGNORED_MODELS:
            openai_models_list = [
                m for m in openai_models_list
                if not any(fnmatch.fnmatch(m['id'], pattern) for pattern in config.IGNORED_MODELS)
            ]

        openai_response = {"object": "list", "data": openai_models_list}
        utils.cached_models_response = openai_response
        return jsonify(openai_response)

    except Exception as e:
        return jsonify({"error": f"Internal server error: {e}"}), 500

@web_ui_chat_bp.route('/api/generate_image', methods=['POST'])
async def generate_image_api():
    form = await request.form
    chat_id = form.get('chat_id', type=int)
    model = form.get('model', 'gemini-1.5-pro-latest')
    prompt = form.get('prompt', '')
    generation_type = form.get('generation_type', 'image')
    result, status_code = await chat_web_logic.generate_image_logic(chat_id, model, prompt, generation_type)
    return jsonify(result), status_code
@web_ui_chat_bp.route('/chat_api', methods=['POST'])
async def chat_api():
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        data, status, error = chat_web_logic.prepare_chat_data(request.form, request.files)
        if error:
            return jsonify(data), status

        chat_id = data['chat_id']
        model = data['model']
        gemini_contents = data['gemini_contents']
        project_context_root = data['project_context_root']
        project_context_tools_requested = data['project_context_tools_requested']
        selected_mcp_tools = data['selected_mcp_tools']
        profile_selected_mcp_tools = data['profile_selected_mcp_tools']
        disable_mcp_tools = data['disable_mcp_tools']
        enable_native_tools = data['enable_native_tools']
        
        # Determine provider: Check registration first to catch custom providers serving Gemini models
        if ai_provider_manager.is_model_registered(model):
            provider = 'openai'
        else:
            provider = utils.get_provider_for_model(model)

        if provider == 'openai':
            async def generate_openai():
                # Reconstruct OpenAI style messages from gemini_contents
                # This is an approximation as gemini_contents are already converted.
                # Ideally we should use raw input but it was processed.
                # Assuming simple conversion back for user/model roles.
                messages = []
                for content in gemini_contents:
                    role = 'user' if content['role'] == 'user' else 'assistant'
                    text = " ".join([p.get('text', '') for p in content['parts'] if 'text' in p])
                    if text:
                        messages.append({"role": role, "content": text})

                # Add system prompt if available (it was injected into first user message in logic usually, 
                # but here we might just prepend if we have access, or it is already in contents)

                while True:
                    request_data = {
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.7
                    }

                    # Tools
                    openai_tools = []
                    builtin_tools = list(mcp_handler.BUILTIN_FUNCTIONS.keys())
                    if project_context_tools_requested:
                        openai_tools.extend(mcp_handler.get_openai_compatible_tools(builtin_tools))
                    elif selected_mcp_tools:
                        openai_tools.extend(mcp_handler.get_openai_compatible_tools(selected_mcp_tools))
                    elif profile_selected_mcp_tools:
                         openai_tools.extend(mcp_handler.get_openai_compatible_tools(profile_selected_mcp_tools))
                    elif not disable_mcp_tools:
                         openai_tools.extend(mcp_handler.get_openai_compatible_tools(builtin_tools))

                    if openai_tools:
                        request_data["tools"] = openai_tools
                        request_data["tool_choice"] = "auto"

                    try:
                        # Resolve provider credentials dynamically
                        provider_conf = ai_provider_manager.get_provider_for_model(model)
                        
                        # Fallback values from config
                        base_url = provider_conf.get('base_url') if provider_conf else config.OPENAI_BASE_URL
                        api_key = provider_conf.get('api_key') if provider_conf else config.OPENAI_API_KEY

                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {api_key}"
                        }
                        print("UPSTREAM OPENAI REQUEST DATA:", json.dumps(request_data, indent=2))
                        
                        async with httpx.AsyncClient(timeout=300.0) as client:
                            async with client.stream(
                                "POST",
                                f"{base_url}/chat/completions",
                                headers=headers,
                                json=request_data
                            ) as response:
                                response.raise_for_status()

                                tool_calls = []
                                current_tool_call = None
                                full_response_text = ""

                                async for line in response.aiter_lines():
                                    if not line: continue
                                    if line.startswith('data: '):
                                        if line == 'data: [DONE]': break
                                        try:
                                            chunk = json.loads(line[6:])
                                            delta = chunk['choices'][0]['delta']

                                            if 'content' in delta and delta['content']:
                                                text = delta['content']
                                                full_response_text += text
                                                yield text

                                            if 'tool_calls' in delta:
                                                for tc in delta['tool_calls']:
                                                    if tc.get('id'):
                                                        if current_tool_call: tool_calls.append(current_tool_call)
                                                        current_tool_call = {
                                                            'id': tc['id'],
                                                            'function': {'name': tc['function'].get('name', ''), 'arguments': tc['function'].get('arguments', '')},
                                                            'type': 'function'
                                                        }
                                                    elif current_tool_call:
                                                        if 'name' in tc['function']: current_tool_call['function']['name'] += tc['function']['name']
                                                        if 'arguments' in tc['function']: current_tool_call['function']['arguments'] += tc['function']['arguments']
                                        except: pass
                    except Exception as e:
                        yield f"ERROR: OpenAI Provider Error: {e}"
                        return

                    if current_tool_call: tool_calls.append(current_tool_call)

                    if full_response_text:
                        utils.add_message_to_db(chat_id, 'model', [{"text": full_response_text}])
                        messages.append({"role": "assistant", "content": full_response_text})

                    if not tool_calls:
                        break

                    # Process tools
                    tool_response_parts = []
                    messages.append({"role": "assistant", "tool_calls": tool_calls})

                    for tool_call in tool_calls:
                        func_name = tool_call['function']['name']
                        try:
                            func_args = json.loads(tool_call['function']['arguments'])
                        except:
                            func_args = {}

                        output = await asyncio.to_thread(mcp_handler.execute_mcp_tool, func_name, func_args, project_context_root)
                        response_payload = json.loads(output) if isinstance(output, str) and output.startswith('{') else {"content": str(output)}
                        tool_response_parts.append({"functionResponse": {"name": func_name, "response": response_payload}})

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call['id'],
                            "name": func_name,
                            "content": str(output)
                        })

                    if tool_response_parts:
                        utils.add_message_to_db(chat_id, 'tool', tool_response_parts)

            from app.utils.core.streaming import async_to_sync_generator
            return Response(async_to_sync_generator(generate_openai()), mimetype='text/event-stream')

        async def generate():
            headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
            current_contents = gemini_contents.copy()
            final_tool_call_response = {}

            while True:
                token_limit = await utils.get_model_input_limit(model, config.API_KEY, config.UPSTREAM_URL)
                safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)

                current_query = ""
                if current_contents:
                    for msg in reversed(current_contents):
                        if msg.get('role') == 'user':
                            current_query = " ".join(p['text'] for p in msg.get('parts', []) if 'text' in p)
                            if current_query:
                                break

                current_contents = utils.truncate_contents(current_contents, safe_limit, current_query=current_query)

                request_data = {
                    "contents": current_contents,
                    "generationConfig": {"temperature": 0.7, "topP": 1.0, "maxOutputTokens": 2048}
                }

                final_tools, mcp_declarations_to_use = [], None
                builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())

                if project_context_tools_requested:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(builtin_tool_names)
                elif selected_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(selected_mcp_tools)
                elif profile_selected_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(profile_selected_mcp_tools)
                elif not disable_mcp_tools:
                    prompt_text = " ".join(p.get("text", "") for m in current_contents for p in m.get("parts", []) if "text" in p)
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations(prompt_text)

                if mcp_declarations_to_use: final_tools.extend(mcp_declarations_to_use)
                if enable_native_tools: final_tools.extend([{"google_search": {}}, {"url_context": {}}])

                if final_tools:
                    request_data["tools"] = final_tools
                    if mcp_declarations_to_use:
                        request_data["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

                tool_calls, model_response_parts = [], []

                if enable_native_tools:
                    GEMINI_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:generateContent"
                    try:
                        print("UPSTREAM GEMINI NATIVE TOOLS REQUEST:", json.dumps(request_data, indent=2))
                        response = utils.make_request_with_retry(url=GEMINI_URL, headers=headers, json_data=request_data, stream=False, timeout=300)
                        response_data = response.json()
                        final_tool_call_response = response_data
                        if not response_data.get('candidates'):
                            yield "The model did not return a response. This could be due to a safety filter."
                        else:
                            candidate = response_data.get('candidates', [{}])[0]
                            model_response_parts = candidate.get('content', {}).get('parts', [])
                            tool_calls = [p['functionCall'] for p in model_response_parts if 'functionCall' in p]
                            full_text = " ".join(p.get('text', '') for p in model_response_parts if 'text' in p)
                            yield full_text
                    except Exception as e:
                        yield f"ERROR: Error from upstream Gemini API: {e}"
                        return
                else:
                    GEMINI_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:streamGenerateContent"
                    try:
                        print("UPSTREAM GEMINI STREAM REQUEST:", json.dumps(request_data, indent=2))
                        async with httpx.AsyncClient(timeout=300.0) as client:
                            async with client.stream(
                                "POST",
                                GEMINI_URL,
                                headers=headers,
                                json=request_data
                            ) as response:
                                response.raise_for_status()

                                buffer, decoder = "", json.JSONDecoder()
                                async for chunk in response.aiter_text():
                                    buffer += chunk
                                    while True:
                                        try:
                                            json_data, end_index = decoder.raw_decode(buffer)
                                            buffer = buffer[end_index:]

                                            responses = json_data if isinstance(json_data, list) else [json_data]

                                            for response_item in responses:
                                                if 'error' in response_item:
                                                    yield "ERROR: " + json.dumps(response_item['error'])
                                                    return
                                                parts = response_item.get('candidates', [{}])[0].get('content', {}).get('parts', [])
                                                model_response_parts.extend(parts)
                                                if 'usageMetadata' in response_item: final_tool_call_response = response_item
                                                for part in parts:
                                                    if 'text' in part: yield part['text']
                                                    if 'functionCall' in part: tool_calls.append(part['functionCall'])
                                        except json.JSONDecodeError:
                                            break
                    except Exception as e:
                        yield f"ERROR: Error from upstream Gemini API: {e}"
                        return

                if not any('text' in p for p in model_response_parts) and not tool_calls and current_contents[-1].get('role') == 'tool':
                    final_text = utils.format_tool_output_for_display(current_contents[-1].get('parts', []))
                    if final_text:
                        model_response_parts = [{'text': final_text}]
                        yield final_text

                if model_response_parts:
                    bot_message_id = utils.add_message_to_db(chat_id, 'model', model_response_parts)
                    yield f'__LLM_EVENT__{json.dumps({"type": "message_id", "id": bot_message_id})}'

                if not tool_calls:
                    usage = final_tool_call_response.get('usageMetadata', {})
                    record_token_usage(headers.get('X-goog-api-key'), model, usage.get('promptTokenCount', 0), usage.get('candidatesTokenCount', 0))
                    break

                current_contents.append({"role": "model", "parts": model_response_parts})

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name, args = tool_call.get("name"), tool_call.get("args")
                    output = await asyncio.to_thread(mcp_handler.execute_mcp_tool, function_name, args, project_context_root)
                    from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                    if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                        output = await utils.summarize_with_aux_model(output, function_name)
                    response_payload = json.loads(output) if isinstance(output, str) and output.startswith('{') else {"content": str(output)}
                    tool_response_parts.append({"functionResponse": {"name": function_name, "response": response_payload}})

                if tool_response_parts:
                    utils.add_message_to_db(chat_id, 'tool', tool_response_parts)
                current_contents.append({"role": "tool", "parts": tool_response_parts})

        from app.utils.core.streaming import async_to_sync_generator
        return Response(async_to_sync_generator(generate()), mimetype='text/event-stream')
    except Exception as e:
        logging.log(f"An error occurred in chat API: {str(e)}")
        return jsonify({"error": f"An error occurred in chat API: {str(e)}"}), 500

@web_ui_chat_bp.route('/uploads/<path:filepath>')
def serve_upload(filepath):
    safe_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filepath))
    if not safe_path.startswith(os.path.abspath(UPLOAD_FOLDER)):
        return "Forbidden", 403
    try:
        return send_from_directory(os.path.dirname(safe_path), os.path.basename(safe_path))
    except FileNotFoundError:
        return "File not found", 404

def get_safe_path(requested_path):
    """Ensure the requested path is within the project root."""
    if not requested_path:
        return None
    
    # Resolve the absolute path of the project root
    project_root = os.path.abspath(config.PROJECT_ROOT) if hasattr(config, 'PROJECT_ROOT') else os.path.abspath(os.getcwd())
    
    # Resolve the absolute path of the requested path
    if os.path.isabs(requested_path):
        safe_path = os.path.abspath(requested_path)
    else:
        safe_path = os.path.abspath(os.path.join(project_root, requested_path))
    
    # Check if the resolved path starts with the project root
    if not safe_path.startswith(project_root):
        return None
        
    return safe_path

@web_ui_chat_bp.route('/api/fs/read', methods=['GET'])
def fs_read_file():
    filepath = request.args.get('path')
    if not filepath:
        return jsonify({"error": "Path parameter is required"}), 400
        
    safe_path = get_safe_path(filepath)
    if not safe_path:
        return jsonify({"error": "Invalid path or permission denied"}), 403
        
    if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(safe_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    except UnicodeDecodeError:
        return jsonify({"error": "File is not standard text (encoding error)"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@web_ui_chat_bp.route('/api/fs/write', methods=['POST'])
def fs_write_file():
    data = request.json
    filepath = data.get('path')
    content = data.get('content')
    
    if not filepath or content is None:
        return jsonify({"error": "Path and content are required"}), 400
        
    safe_path = get_safe_path(filepath)
    if not safe_path:
        return jsonify({"error": "Invalid path or permission denied"}), 403
        
    try:
        # Create backup if file exists
        if os.path.exists(safe_path) and os.path.isfile(safe_path):
            backup_path = safe_path + '.bak'
            import shutil
            shutil.copy2(safe_path, backup_path)
            
        # Write new content
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@web_ui_chat_bp.route('/api/fs/revert', methods=['POST'])
def fs_revert_file():
    data = request.json
    filepath = data.get('path')
    
    if not filepath:
        return jsonify({"error": "Path is required"}), 400
        
    safe_path = get_safe_path(filepath)
    if not safe_path:
        return jsonify({"error": "Invalid path or permission denied"}), 403
        
    backup_path = safe_path + '.bak'
    if not os.path.exists(backup_path):
        return jsonify({"error": "No backup found to revert"}), 404
        
    try:
        import shutil
        shutil.copy2(backup_path, safe_path)
        return jsonify({"success": True})
    except Exception as e:
         return jsonify({"error": str(e)}), 500
