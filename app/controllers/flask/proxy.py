import json
import os
import time
import requests
from flask import Blueprint, request, jsonify, Response
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException

from app.config import config
from app.utils.flask import optimization
from app.utils.core import mcp_handler, tools as utils
from app.utils.core import tool_config_utils
from app.utils.flask.optimization import record_token_usage
from app.utils.core.optimization_utils import can_execute_parallel

import traceback
from app.utils.core import file_processing_utils
proxy_bp = Blueprint('proxy', __name__)
@proxy_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        openai_request = request.json
        utils.debug(f"Incoming Request: {utils.pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])

        disable_mcp_tools = False
        enable_native_tools = False
        project_system_context_text = None
        profile_selected_mcp_tools = []

        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            disable_mcp_tools = True
            profile_selected_mcp_tools = []

        if messages:
            full_prompt_text = " ".join(
                [m.get('content') for m in messages if isinstance(m.get('content'), str)]
            )

            override_config = tool_config_utils.get_prompt_override_config(full_prompt_text)
            active_overrides = override_config['active_overrides']

            if override_config['disable_mcp_tools_by_profile']:
                disable_mcp_tools = True

            if override_config['enable_native_tools_by_profile']:
                enable_native_tools = True

            if override_config['profile_selected_mcp_tools']:
                profile_selected_mcp_tools = override_config['profile_selected_mcp_tools']

            project_context_tools_requested = False
            project_context_root = None
            processed_messages = []
            processed_code_paths = set()

            for message in messages:
                content = message.get('content')

                if isinstance(content, str):
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    if not disable_mcp_tools:
                        processed_content, project_path_found, project_system_context = file_processing_utils.process_message_for_paths(
                            content, processed_code_paths
                        )
                        message['content'] = processed_content
                        if project_path_found:
                            project_context_tools_requested = True
                            if isinstance(project_path_found, str):
                                project_system_context_text = project_system_context
                                project_context_root = project_path_found

                processed_messages.append(message)

            messages = processed_messages
        else:
            full_prompt_text = ""

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        system_instruction = None

        gemini_contents = []
        if messages:
            if project_system_context_text:
                system_instruction = {"parts": [{"text": project_system_context_text}]}
                if 'JetBrains' in messages[0].get("content"):
                    messages = messages[1:]
            elif messages[0].get("role") == "system" or 'JetBrains' in messages[0].get("content"):
                system_instruction = {"parts": [{"text": messages[0].get("content", "")}]}
                messages = messages[1:]

            mapped_messages = []
            for message in messages:
                role = "model" if message.get("role") == "assistant" else "user"
                content = message.get("content")

                gemini_parts = []
                if isinstance(content, str):
                    if content:
                        gemini_parts.append({"text": content})
                elif isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            if text_parts:
                                gemini_parts.append({"text": "\n".join(text_parts)})
                                text_parts = []

                            image_part = utils._process_image_url(part.get("image_url", {}))
                            if image_part:
                                gemini_parts.append(image_part)
                        elif part.get("type") == "inline_data":
                            if text_parts:
                                gemini_parts.append({"text": "\n".join(text_parts)})
                                text_parts = []
                            source = part.get("source", {})
                            gemini_parts.append({
                                "inlineData": {
                                    "mimeType": source.get("media_type"),
                                    "data": source.get("data")
                                }
                            })

                    if text_parts:
                        gemini_parts.append({"text": "\n".join(text_parts)})

                if gemini_parts:
                    mapped_messages.append({"role": role, "parts": gemini_parts})

            if mapped_messages:
                gemini_contents.append(mapped_messages[0])
                for i in range(1, len(mapped_messages)):
                    if mapped_messages[i]['role'] == gemini_contents[-1]['role']:
                        gemini_contents[-1]['parts'].extend(mapped_messages[i]['parts'])
                    else:
                        gemini_contents.append(mapped_messages[i])

            for content in gemini_contents:
                original_parts = content.get('parts', [])
                if len(original_parts) > 1:
                    merged_parts = []
                    text_buffer = []
                    for part in original_parts:
                        is_text_part = 'text' in part and len(part) == 1
                        if is_text_part:
                            text_buffer.append(part['text'])
                        else:
                            if text_buffer:
                                merged_parts.append({'text': '\n'.join(text_buffer)})
                                text_buffer = []
                            merged_parts.append(part)

                    if text_buffer:
                        merged_parts.append({'text': '\n'.join(text_buffer)})

                    content['parts'] = merged_parts

        token_limit = utils.get_model_input_limit(COMPLETION_MODEL, config.API_KEY, config.UPSTREAM_URL)
        safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)

        def generate():
            current_contents = gemini_contents.copy()
            final_usage_metadata = {}

            while True:
                original_message_count = len(current_contents)

                current_query = ""
                if current_contents:
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
                    utils.log(f"Truncated conversation from {original_message_count} to {len(current_contents)} messages to fit context window.")

                request_data = {
                    "contents": current_contents
                }

                cached_context_id = None
                if system_instruction:
                    system_text = ""
                    for part in system_instruction.get("parts", []):
                        if "text" in part:
                            system_text += part["text"]

                    if system_text and utils.estimate_token_count([system_instruction]) >= config.MIN_CONTEXT_CACHING_TOKENS:
                        try:
                            cached_context_id = optimization.get_cached_context_id(
                                config.API_KEY,
                                config.UPSTREAM_URL,
                                COMPLETION_MODEL,
                                system_text
                            )
                            if cached_context_id:
                                utils.log(f"✓ Using cached context: {cached_context_id}")
                                request_data["cachedContent"] = cached_context_id
                            else:
                                request_data["systemInstruction"] = system_instruction
                        except Exception as e:
                            utils.log(f"Failed to use cached context, falling back to normal: {e}")
                            request_data["systemInstruction"] = system_instruction
                    else:
                        request_data["systemInstruction"] = system_instruction

                final_tools = []
                mcp_declarations_to_use = None

                builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())

                if project_context_tools_requested and not disable_mcp_tools and not mcp_handler.disable_all_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(builtin_tool_names)
                    utils.log(f"Project context activated via project_path=. Forcing use of built-in tools: {builtin_tool_names}")
                elif not disable_mcp_tools and profile_selected_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(profile_selected_mcp_tools)
                    utils.log(f"Using MCP tools defined by prompt override profile: {profile_selected_mcp_tools}")
                elif disable_mcp_tools:
                    utils.log(f"MCP Tools explicitly disabled by profile or global setting.")
                else:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations(full_prompt_text)
                    utils.log(f"MCP tools enabled. Using context-aware selection based on prompt.")

                if mcp_declarations_to_use:
                    final_tools.extend(mcp_declarations_to_use)

                if enable_native_tools:
                    final_tools.append({"google_search": {}})
                    final_tools.append({"url_context": {}})
                    utils.log("Added google_search and url_context to tools.")

                if final_tools:
                    request_data["tools"] = final_tools
                    if not enable_native_tools:
                        request_data["tool_config"] = {
                            "function_calling_config": {
                                "mode": "AUTO"
                            }
                        }

                GEMINI_STREAMING_URL = f"{config.UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"
                headers = {
                    'Content-Type': 'application/json',
                    'X-goog-api-key': config.API_KEY
                }

                utils.debug(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
                utils.debug(f"Outgoing Gemini Request Data: {utils.pretty_json(request_data)}")

                response = None
                try:
                    response = utils.make_request_with_retry(
                        url=GEMINI_STREAMING_URL,
                        headers=headers,
                        json_data=request_data,
                        stream=True,
                        timeout=300
                    )
                except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                    error_message = f"Error from upstream Gemini API: {e}"
                    utils.log(error_message)
                    error_chunk = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": COMPLETION_MODEL,
                        "choices": [{"index": 0, "delta": {"content": error_message}, "finish_reason": "stop"}]
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                buffer = ""
                tool_calls = []
                model_response_parts = []
                decoder = json.JSONDecoder()

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
                                error_message = "Error from upstream Gemini API: " + json.dumps(json_data['error'])
                                utils.log(error_message)
                                error_chunk = {
                                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": COMPLETION_MODEL,
                                    "choices": [{"index": 0, "delta": {"content": error_message}, "finish_reason": "stop"}]
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return

                            if 'usageMetadata' in json_data:
                                final_usage_metadata.update(json_data['usageMetadata'])

                            parts = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])

                            if not parts and 'usageMetadata' in json_data:
                                continue
                            else:
                                model_response_parts.extend(parts)
                                text_content = ""
                                for part in parts:
                                    if 'text' in part:
                                        text_content += part['text']
                                    if 'functionCall' in part:
                                        tool_calls.append(part['functionCall'])

                                if text_content:
                                    chunk_response = {
                                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": COMPLETION_MODEL,
                                        "choices": [{"index": 0, "delta": {"content": text_content}, "finish_reason": None}]
                                    }
                                    utils.debug(f"Active Proxy Response Chunk: {utils.pretty_json(chunk_response)}")
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                        except json.JSONDecodeError:
                            if len(buffer) > 65536: buffer = buffer[-32768:]
                            break
                is_after_tool_call = current_contents and current_contents[-1].get('role') == 'tool'
                has_text_in_model_response = any('text' in p for p in model_response_parts)

                if is_after_tool_call and not has_text_in_model_response and not tool_calls:
                    tool_parts_from_history = current_contents[-1].get('parts', [])
                    final_text = utils.format_tool_output_for_display(tool_parts_from_history, False)

                    if final_text:
                        model_response_parts = [{'text': final_text}]
                        tool_output_chunk = {
                            "id": f"chatcmpl-{os.urandom(12).hex()}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": COMPLETION_MODEL,
                            "choices": [{"index": 0, "delta": {"content": final_text}, "finish_reason": None}]
                        }
                        utils.log(f"Silent Model Proxy Tool Output Chunk: {utils.pretty_json(tool_output_chunk)}")
                        yield f"data: {json.dumps(tool_output_chunk)}\n\n"

                if not tool_calls:
                    break

                utils.debug(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({
                    "role": "model",
                    "parts": model_response_parts
                })

                tool_response_parts = []

                if can_execute_parallel(tool_calls):
                    utils.log(f"✓ Executing {len(tool_calls)} tools in parallel")

                    parallel_calls = []
                    for tool_call in tool_calls:
                        parallel_calls.append({
                            'name': tool_call.get("name"),
                            'args': tool_call.get("args")
                        })

                    results = optimization.execute_tools_parallel(parallel_calls, project_context_root)

                    for tool_call_data, output in results:
                        function_name = tool_call_data['name']

                        from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                        if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                            output = utils.summarize_with_aux_model(output, function_name)

                        response_payload = {}
                        if output is not None:
                            try:
                                response_payload = json.loads(output)
                            except (json.JSONDecodeError, TypeError):
                                response_payload = {"content": str(output)}
                        else:
                            response_payload = {}

                        tool_response_parts.append({
                            "functionResponse": {
                                "name": function_name,
                                "response": response_payload
                            }
                        })

                else:
                    utils.log(f"✓ Executing {len(tool_calls)} tools sequentially")

                    for tool_call in tool_calls:
                        function_name = tool_call.get("name")
                        tool_args = tool_call.get("args")

                        args_str = json.dumps(tool_args)
                        feedback_message = f"🔍 Assistant is using tool: {function_name}({args_str})"
                        utils.log(feedback_message)

                        output = mcp_handler.execute_mcp_tool(function_name, tool_args, project_context_root)

                        from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                        if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                            output = utils.summarize_with_aux_model(output, function_name)

                        response_payload = {}
                        if output is not None:
                            try:
                                response_payload = json.loads(output)
                            except (json.JSONDecodeError, TypeError):
                                response_payload = {"content": str(output)}
                        else:
                            response_payload = {}

                        tool_response_parts.append({
                            "functionResponse": {
                                "name": function_name,
                                "response": response_payload
                            }
                        })

                current_contents.append({
                    "role": "tool",
                    "parts": tool_response_parts
                })

            api_key_header = headers.get('X-goog-api-key') or config.API_KEY
            model_name = COMPLETION_MODEL

            usage_metadata = final_usage_metadata
            input_tokens = usage_metadata.get('promptTokenCount', 0)
            output_tokens = usage_metadata.get('candidatesTokenCount', 0)

            record_token_usage(api_key_header, model_name, input_tokens, output_tokens)

            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            utils.debug(f"Final Proxy Response Chunk: {utils.pretty_json(final_chunk)}")
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        utils.log(f"An error occurred during chat completion: {e}\n{traceback.format_exc()}")
        error_message = f"An error occurred: {str(e)}"
        error_response = {"error": {"message": error_message, "type": "server_error", "code": "500"}}
        return jsonify(error_response), 500
@proxy_bp.route('/v1/models', methods=['GET'])
def list_models():
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        if utils.cached_models_response:
            return jsonify(utils.cached_models_response)

        params = {"key": config.API_KEY}
        GEMINI_MODELS_URL = f"{config.UPSTREAM_URL}/v1beta/models"
        response = requests.get(GEMINI_MODELS_URL, params=params)
        response.raise_for_status()
        gemini_models_data = response.json()

        openai_models_list = []
        for model in gemini_models_data.get("models", []):
            if "generateContent" in model.get("supportedGenerationMethods", []):
                openai_models_list.append({
                    "id": model["name"].split("/")[-1], "object": "model",
                    "created": 1677649553, "owned_by": "google", "permission": []
                })
        openai_response = {"object": "list", "data": openai_models_list}
        utils.cached_models_response = openai_response
        return jsonify(openai_response)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error fetching models from Gemini API: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"Internal server error: {e}"}), 500
