import json
import os
from flask import Blueprint, request, jsonify, Response, send_from_directory
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
from app.config import config
from app.utils.core import mcp_handler, tools as utils, logging, chat_db_utils
from app.db import UPLOAD_FOLDER
from app.utils.flask.optimization import record_token_usage
from app.utils.core import chat_web_logic
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
@web_ui_chat_bp.route('/api/generate_image', methods=['POST'])
def generate_image_api():
    form = request.form
    chat_id = form.get('chat_id', type=int)
    model = form.get('model', 'gemini-1.5-pro-latest')
    prompt = form.get('prompt', '')
    generation_type = form.get('generation_type', 'image')
    result, status_code = chat_web_logic.generate_image_logic(chat_id, model, prompt, generation_type)
    return jsonify(result), status_code
@web_ui_chat_bp.route('/chat_api', methods=['POST'])
def chat_api():
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

        if utils.get_provider_for_model(model) == 'openai':
            def generate_openai():
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
                        "model": config.OPENAI_MODEL_NAME,
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
                        import requests
                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {config.OPENAI_API_KEY}"
                        }
                        response = requests.post(
                            f"{config.OPENAI_BASE_URL}/chat/completions",
                            headers=headers,
                            json=request_data,
                            stream=True,
                            timeout=300
                        )
                        response.raise_for_status()
                    except Exception as e:
                        yield f"ERROR: OpenAI Provider: {e}"
                        return

                    tool_calls = []
                    current_tool_call = None
                    full_response_text = ""

                    for line in response.iter_lines():
                        if not line: continue
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith('data: '):
                            if decoded_line == 'data: [DONE]': break
                            try:
                                chunk = json.loads(decoded_line[6:])
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

                        output = mcp_handler.execute_mcp_tool(func_name, func_args, project_context_root)
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

            return Response(generate_openai(), mimetype='text/event-stream')

        def generate():
            headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
            current_contents = gemini_contents.copy()
            final_tool_call_response = {}

            while True:
                token_limit = utils.get_model_input_limit(model, config.API_KEY, config.UPSTREAM_URL)
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
                        response = utils.make_request_with_retry(url=GEMINI_URL, headers=headers, json_data=request_data, stream=True, timeout=300)
                    except Exception as e:
                        yield f"ERROR: Error from upstream Gemini API: {e}"
                        return

                    buffer, decoder = "", json.JSONDecoder()
                    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
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
                    output = mcp_handler.execute_mcp_tool(function_name, args, project_context_root)
                    from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                    if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                        output = utils.summarize_with_aux_model(output, function_name)
                    response_payload = json.loads(output) if isinstance(output, str) and output.startswith('{') else {"content": str(output)}
                    tool_response_parts.append({"functionResponse": {"name": function_name, "response": response_payload}})

                if tool_response_parts:
                    utils.add_message_to_db(chat_id, 'tool', tool_response_parts)
                current_contents.append({"role": "tool", "parts": tool_response_parts})

        return Response(generate(), mimetype='text/event-stream')
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
