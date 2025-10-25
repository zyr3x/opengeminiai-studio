"""
Async Quart routes for the OpenAI-compatible proxy endpoints.
"""
import json
import os
import time
from quart import Blueprint, request, jsonify, Response
from typing import AsyncGenerator
from app.config import config
from app.utils.core import tools as utils
from app.utils.core import tool_config_utils
from app.utils.quart import mcp_handler, optimization, utils
import traceback

async_proxy_bp = Blueprint('proxy', __name__)

@async_proxy_bp.route('/v1/chat/completions', methods=['POST'])
async def async_chat_completions():
    """
    Async version: Handles chat completion requests with improved concurrency.
    """
    if not config.API_KEY:
        return jsonify({
            "error": {
                "message": "API key not configured. Please set it on the root page.",
                "type": "invalid_request_error",
                "code": "api_key_not_set"
            }
        }), 401
    
    try:
        openai_request = await request.json
        utils.debug(f"Incoming Request: {utils.pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])

        # --- Prompt Engineering & Tool Control ---
        disable_mcp_tools = False
        enable_native_tools = False
        profile_selected_mcp_tools = []

        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            disable_mcp_tools = True
            profile_selected_mcp_tools = []

        code_tools_requested = False
        code_project_root = None
        full_prompt_text = ""

        if messages:
            # Identify prompt profile
            full_prompt_text = " ".join(
                [m.get('content') for m in messages if isinstance(m.get('content'), str)]
            )

            # Apply Prompt Engineering & Tool Control Overrides
            override_config = tool_config_utils.get_prompt_override_config(full_prompt_text)
            active_overrides = override_config['active_overrides']

            if override_config['disable_mcp_tools_by_profile']:
                disable_mcp_tools = True

            if override_config['enable_native_tools_by_profile']:
                enable_native_tools = True

            if override_config['profile_selected_mcp_tools']:
                profile_selected_mcp_tools = override_config['profile_selected_mcp_tools']

            # Process messages - file processing
            from app.utils.core.tools import file_processing_utils
            processed_messages = []

            for message in messages:
                content = message.get('content')

                if isinstance(content, str):
                    # Apply overrides
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    # Handle local file paths
                    processed_result = None
                    if not disable_mcp_tools:
                        processed_result = file_processing_utils.process_message_for_paths(content)

                        if isinstance(processed_result, tuple):
                            message['content'], code_path_value = processed_result
                            if code_path_value:
                                code_tools_requested = True
                                if isinstance(code_path_value, str):
                                    code_project_root = code_path_value
                        else:
                            message['content'] = processed_result

                processed_messages.append(message)

            messages = processed_messages

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        system_instruction = None

        # Transform messages to Gemini format
        gemini_contents = []
        if messages:
            # Separate system instruction
            if messages[0].get("role") == "system":
                system_instruction = {"parts": [{"text": messages[0].get("content", "")}]}
                messages = messages[1:]

            # Map roles and merge consecutive messages
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

                            # Use async image processing
                            image_part = await utils.process_image_url_async(
                                part.get("image_url", {})
                            )
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

            # Merge consecutive messages with same role
            if mapped_messages:
                gemini_contents.append(mapped_messages[0])
                for i in range(1, len(mapped_messages)):
                    if mapped_messages[i]['role'] == gemini_contents[-1]['role']:
                        gemini_contents[-1]['parts'].extend(mapped_messages[i]['parts'])
                    else:
                        gemini_contents.append(mapped_messages[i])

            # Merge consecutive text parts
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

        # --- Token Management ---
        token_limit = await utils.get_model_input_limit_async(
            COMPLETION_MODEL, config.API_KEY, config.UPSTREAM_URL
        )
        safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)

        # Use async generator for streaming response
        async def generate() -> AsyncGenerator[str, None]:
            current_contents = gemini_contents.copy()
            final_usage_metadata = {}

            while True:  # Loop for sequential tool calls
                # Truncate messages
                original_message_count = len(current_contents)
                
                # Extract current query for selective context
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
                
                current_contents = await utils.truncate_contents_async(
                    current_contents, safe_limit, current_query=current_query
                )
                
                if len(current_contents) < original_message_count:
                    utils.log(
                        f"Truncated conversation from {original_message_count} to "
                        f"{len(current_contents)} messages to fit context window."
                    )

                request_data = {
                    "contents": current_contents
                }
                
                # --- Prompt Caching ---
                cached_context_id = None
                if system_instruction:
                    system_text = ""
                    for part in system_instruction.get("parts", []):
                        if "text" in part:
                            system_text += part["text"]
                    
                    if system_text and len(system_text) > 500:
                        try:
                            cached_context_id = await optimization.get_cached_context_id_async(
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
                            utils.log(f"Failed to use cached context: {e}")
                            request_data["systemInstruction"] = system_instruction
                    else:
                        request_data["systemInstruction"] = system_instruction
                elif system_instruction:
                    request_data["systemInstruction"] = system_instruction

                # --- Tool Configuration ---
                final_tools = []
                mcp_declarations_to_use = None

                builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())

                if code_tools_requested and not disable_mcp_tools and not mcp_handler.disable_all_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(
                        builtin_tool_names
                    )
                    utils.log(
                        f"Code context requested. Forcing use of built-in tools: {builtin_tool_names}"
                    )
                elif not disable_mcp_tools and profile_selected_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(
                        profile_selected_mcp_tools
                    )
                    utils.log(
                        f"Using MCP tools defined by profile: {profile_selected_mcp_tools}"
                    )
                elif disable_mcp_tools:
                    utils.log("MCP Tools disabled by profile or global setting.")
                else:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations(full_prompt_text)
                    utils.log("MCP tools enabled. Using context-aware selection.")

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

                GEMINI_STREAMING_URL = (
                    f"{config.UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"
                )
                headers = {
                    'Content-Type': 'application/json',
                    'X-goog-api-key': config.API_KEY
                }

                utils.debug(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
                utils.debug(f"Outgoing Gemini Request Data: {utils.pretty_json(request_data)}")

                # Apply rate limiting
                rate_limiter = await optimization.get_rate_limiter()
                await rate_limiter.wait_if_needed()

                # Make async request
                try:
                    response = await utils.make_request_with_retry_async(
                        url=GEMINI_STREAMING_URL,
                        headers=headers,
                        json_data=request_data,
                        stream=True,
                        timeout=300
                    )
                except Exception as e:
                    error_message = f"Error from upstream Gemini API: {e}"
                    utils.log(error_message)
                    error_chunk = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": COMPLETION_MODEL,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": error_message},
                            "finish_reason": "stop"
                        }]
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Process streaming response
                buffer = ""
                tool_calls = []
                model_response_parts = []
                decoder = json.JSONDecoder()

                async for chunk in response.content.iter_any():
                    chunk_text = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                    buffer += chunk_text
                    
                    while True:
                        start_index = buffer.find('{')
                        if start_index == -1:
                            if len(buffer) > 65536:
                                buffer = buffer[-32768:]
                            break
                        buffer = buffer[start_index:]
                        
                        try:
                            json_data, end_index = decoder.raw_decode(buffer)
                            buffer = buffer[end_index:]
                            
                            if not isinstance(json_data, dict):
                                continue

                            if 'error' in json_data:
                                error_message = "Error from Gemini: " + json.dumps(json_data['error'])
                                utils.log(error_message)
                                error_chunk = {
                                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": COMPLETION_MODEL,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": error_message},
                                        "finish_reason": "stop"
                                    }]
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return

                            # Check usage metadata
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
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": text_content},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                    
                        except json.JSONDecodeError:
                            if len(buffer) > 65536:
                                buffer = buffer[-32768:]
                            break

                # Handle silent model after tool call
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
                            "choices": [{
                                "index": 0,
                                "delta": {"content": final_text},
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(tool_output_chunk)}\n\n"

                if not tool_calls:
                    break

                utils.debug(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({
                    "role": "model",
                    "parts": model_response_parts
                })

                # Execute tools async (parallel when possible)
                tool_calls_list = [
                    {'name': tc.get('name'), 'args': tc.get('args')}
                    for tc in tool_calls
                ]

                # Set project root context if needed
                if code_project_root:
                    with mcp_handler.set_project_root(code_project_root):
                        tool_response_parts = await mcp_handler.execute_multiple_tools_async(
                            tool_calls_list
                        )
                else:
                    tool_response_parts = await mcp_handler.execute_multiple_tools_async(
                        tool_calls_list
                    )

                current_contents.append({
                    "role": "tool",
                    "parts": tool_response_parts
                })

            # Record token usage
            await optimization.record_token_usage_async(
                config.API_KEY,
                COMPLETION_MODEL,
                final_usage_metadata.get('promptTokenCount', 0),
                final_usage_metadata.get('candidatesTokenCount', 0)
            )

            # Send final chunk
            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        utils.log(f"Error during chat completion: {e}\n{traceback.format_exc()}")
        error_response = {
            "error": {
                "message": f"An error occurred: {str(e)}",
                "type": "server_error",
                "code": "500"
            }
        }
        return jsonify(error_response), 500

@async_proxy_bp.route('/v1/models', methods=['GET'])
async def async_list_models():
    """
    Async version: Fetches the list of available models from Gemini API.
    """
    if not config.API_KEY:
        return jsonify({
            "error": {
                "message": "API key not configured.",
                "type": "invalid_request_error",
                "code": "api_key_not_set"
            }
        }), 401
    
    try:
        # Check cache first
        if utils.cached_models_response:
            return jsonify(utils.cached_models_response)

        params = {"key": config.API_KEY}
        GEMINI_MODELS_URL = f"{config.UPSTREAM_URL}/v1beta/models"
        
        session = await utils.get_async_session()
        async with session.get(GEMINI_MODELS_URL, params=params) as response:
            response.raise_for_status()
            gemini_models_data = await response.json()

        openai_models_list = []
        for model in gemini_models_data.get("models", []):
            if "generateContent" in model.get("supportedGenerationMethods", []):
                openai_models_list.append({
                    "id": model["name"].split("/")[-1],
                    "object": "model",
                    "created": 1677649553,
                    "owned_by": "google",
                    "permission": []
                })
        
        openai_response = {"object": "list", "data": openai_models_list}
        utils.cached_models_response = openai_response
        return jsonify(openai_response)

    except Exception as e:
        return jsonify({"error": f"Error fetching models: {e}"}), 500
