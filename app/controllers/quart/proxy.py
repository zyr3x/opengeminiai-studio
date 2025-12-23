import json
import os
import time
import fnmatch
from quart import Blueprint, request, jsonify, Response
from typing import AsyncGenerator
from app.config import config
from app.utils.core import tools as utils
from app.utils.core import tool_config_utils
from app.utils.quart import optimization, utils as quart_utils, mcp_handler as async_mcp_handler
from app.utils.core import mcp_handler
from app.utils.core import patch_utils
import traceback
async_proxy_bp = Blueprint('proxy', __name__)
@async_proxy_bp.route('/v1/chat/completions', methods=['POST'])
async def async_chat_completions():
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

        disable_mcp_tools = False
        enable_native_tools = False
        profile_selected_mcp_tools = []

        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            disable_mcp_tools = True
            profile_selected_mcp_tools = []

        project_context_tools_requested = False
        project_context_root = None
        project_system_context_text = None
        full_prompt_text = ""
        editing_mode = False

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

            from app.utils.core import file_processing_utils
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
                        processed_content, project_path_found, new_system_context = file_processing_utils.process_message_for_paths(
                            content, processed_code_paths
                        )
                        if config.QUICK_EDIT_ENABLED and 'code_path=' in content:
                            editing_mode = True

                        message['content'] = processed_content
                        if new_system_context:
                            project_system_context_text = new_system_context

                        if project_path_found:
                            project_context_tools_requested = True
                            if isinstance(project_path_found, str):
                                project_context_root = project_path_found

                processed_messages.append(message)

            messages = processed_messages

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        provider = utils.get_provider_for_model(COMPLETION_MODEL)

        if provider == 'openai':
            async def generate_openai():
                current_messages = messages.copy()
                # Inject system prompt if needed
                if project_system_context_text:
                    current_messages.insert(0, {"role": "system", "content": project_system_context_text})
                
                # Editing mode instruction
                if editing_mode:
                    edit_instruction = (
                        "\n\n**CRITICAL: EDITING MODE IS ACTIVE. IGNORE OTHER EDITING INSTRUCTIONS.**\n\n"
                        "You are in a special editing mode. Your primary goal is to modify files based on the user's request. To do this, you MUST use the following patch format:\n\n"
                        "File: `path/to/file`\n"
                        "<<<<<<< SEARCH\n"
                        "[content to be replaced]\n"
                        "=======\n"
                        "[new content]\n"
                        ">>>>>>> REPLACE\n\n"
                    )
                    # Find system message or insert one
                    sys_msg_idx = next((i for i, m in enumerate(current_messages) if m['role'] == 'system'), None)
                    if sys_msg_idx is not None:
                        current_messages[sys_msg_idx]['content'] = edit_instruction + current_messages[sys_msg_idx]['content']
                    else:
                        current_messages.insert(0, {"role": "system", "content": edit_instruction})

                while True:
                    request_data = {
                        "model": COMPLETION_MODEL,
                        "messages": current_messages,
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
                        session = await quart_utils.get_async_session()
                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {config.OPENAI_API_KEY}"
                        }
                        
                        # Note: This uses aiohttp session which is async
                        async with session.post(
                            f"{config.OPENAI_BASE_URL}/chat/completions",
                            headers=headers,
                            json=request_data,
                            timeout=300
                        ) as response:
                            response.raise_for_status()
                            
                            tool_calls = []
                            current_tool_call = None
                            full_response_text = ""
                            
                            async for line in response.content:
                                if not line: continue
                                decoded_line = line.decode('utf-8').strip()
                                if decoded_line.startswith('data: '):
                                    if decoded_line == 'data: [DONE]': break
                                    try:
                                        chunk = json.loads(decoded_line[6:])
                                        delta = chunk['choices'][0]['delta']
                                        finish_reason = chunk['choices'][0].get('finish_reason')

                                        if 'content' in delta and delta['content']:
                                            content_chunk = delta['content']
                                            full_response_text += content_chunk
                                            yield f"data: {json.dumps(chunk)}\n\n"
                                        elif finish_reason and finish_reason != 'tool_calls':
                                            yield f"data: {json.dumps(chunk)}\n\n"
                                        
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
                            
                            if editing_mode and full_response_text:
                                cleaned_text, changes = patch_utils.apply_patches(full_response_text)
                                # Cleaned text handling if needed
                            
                            if not tool_calls:
                                yield "data: [DONE]\n\n"
                                return # Break out of while loop
                                
                            # Process tools
                            current_messages.append({"role": "assistant", "content": full_response_text, "tool_calls": tool_calls})
                            
                            tool_calls_list = [{'name': tc['function']['name'], 'args': json.loads(tc['function']['arguments'])} for tc in tool_calls]
                            
                            tool_results = await async_mcp_handler.execute_multiple_tools_async(tool_calls_list, project_context_root)
                            
                            for i, result_part in enumerate(tool_results):
                                func_name = tool_calls[i]['function']['name']
                                output = result_part['functionResponse']['response']
                                if isinstance(output, dict) and 'content' in output:
                                    output = output['content']
                                else:
                                    output = json.dumps(output)
                                    
                                current_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_calls[i]['id'],
                                    "name": func_name,
                                    "content": str(output)
                                })

                    except Exception as e:
                        err_msg = f"OpenAI Provider Error: {e}"
                        utils.log(err_msg)
                        error_chunk = {
                            "id": f"chatcmpl-{os.urandom(12).hex()}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": COMPLETION_MODEL,
                            "choices": [{"index": 0, "delta": {"content": err_msg}, "finish_reason": "stop"}]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

            return Response(generate_openai(), mimetype='text/event-stream')

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
            
            if editing_mode:
                edit_instruction = (
                    "\n\n**CRITICAL: EDITING MODE IS ACTIVE. IGNORE OTHER EDITING INSTRUCTIONS.**\n\n"
                    "You are in a special editing mode. Your primary goal is to modify files based on the user's request. To do this, you MUST use the following patch format:\n\n"
                    "File: `path/to/file`\n"
                    "<<<<<<< SEARCH\n"
                    "[content to be replaced]\n"
                    "=======\n"
                    "[new content]\n"
                    ">>>>>>> REPLACE\n\n"
                    "**IMPORTANT RULES:**\n"
                    "1. The system will apply your patch, tolerating minor differences in the source file.\n"
                    "2. Your response to the user should ONLY contain your answer/explanation. Do NOT include the patch blocks in your final response, as they are processed automatically.\n"
                )
                if system_instruction and system_instruction.get('parts'):
                    system_instruction['parts'][0]['text'] = edit_instruction + system_instruction['parts'][0]['text']
                else:
                    system_instruction = {"parts": [{"text": edit_instruction}]}

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

                            image_part = await quart_utils.process_image_url_async(
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

        token_limit = await quart_utils.get_model_input_limit_async(
            COMPLETION_MODEL, config.API_KEY, config.UPSTREAM_URL
        )
        safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)

        async def generate() -> AsyncGenerator[str, None]:
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

                current_contents = await quart_utils.truncate_contents_async(
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

                cached_context_id = None
                if system_instruction:
                    system_text = ""
                    for part in system_instruction.get("parts", []):
                        if "text" in part:
                            system_text += part["text"]

                    if system_text and utils.estimate_token_count([system_instruction]) >= config.MIN_CONTEXT_CACHING_TOKENS:
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
                            utils.log(f"Failed to use cached context, falling back to normal: {e}")
                            request_data["systemInstruction"] = system_instruction
                    else:
                        request_data["systemInstruction"] = system_instruction

                final_tools = []
                mcp_declarations_to_use = None

                builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())

                if project_context_tools_requested and not disable_mcp_tools and not mcp_handler.disable_all_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(
                        builtin_tool_names
                    )
                    utils.log(
                        f"Project context activated via project_path=. Forcing use of built-in tools: {builtin_tool_names}"
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

                rate_limiter = await optimization.get_rate_limiter()
                await rate_limiter.wait_if_needed()

                try:
                    response = await quart_utils.make_request_with_retry_async(
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
                        yield f"data: {json.dumps(tool_output_chunk)}\n\n"

                if not tool_calls:
                    break

                utils.debug(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({
                    "role": "model",
                    "parts": model_response_parts
                })

                tool_calls_list = [
                    {'name': tc.get('name'), 'args': tc.get('args')}
                    for tc in tool_calls
                ]

                tool_response_parts = await async_mcp_handler.execute_multiple_tools_async(
                    tool_calls_list,
                    project_root_override=project_context_root
                )

                current_contents.append({
                    "role": "tool",
                    "parts": tool_response_parts
                })

            await optimization.record_token_usage_async(
                config.API_KEY,
                COMPLETION_MODEL,
                final_usage_metadata.get('promptTokenCount', 0),
                final_usage_metadata.get('candidatesTokenCount', 0)
            )

            if editing_mode:
                # In editing mode, we buffer the entire response to apply patches
                full_response_text = ""
                for content in current_contents:
                    if content.get('role') == 'model':
                        for part in content.get('parts', []):
                            if 'text' in part:
                                full_response_text += part['text']
                
                # Apply patches
                cleaned_text, changes = patch_utils.apply_patches(full_response_text)
                
                # Send the cleaned response
                final_chunk = {
                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": COMPLETION_MODEL,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": cleaned_text},
                        "finish_reason": "stop"
                    }]
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return

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
    if not config.API_KEY:
        return jsonify({
            "error": {
                "message": "API key not configured.",
                "type": "invalid_request_error",
                "code": "api_key_not_set"
            }
        }), 401

    try:
        if utils.cached_models_response:
            return jsonify(utils.cached_models_response)

        openai_models_list = []
        session = await quart_utils.get_async_session()

        # 1. Fetch Gemini Models
        try:
            params = {"key": config.API_KEY}
            GEMINI_MODELS_URL = f"{config.UPSTREAM_URL}/v1beta/models"

            async with session.get(GEMINI_MODELS_URL, params=params) as response:
                response.raise_for_status()
                gemini_models_data = await response.json()

            for model in gemini_models_data.get("models", []):
                if "generateContent" in model.get("supportedGenerationMethods", []):
                    openai_models_list.append({
                        "id": model["name"].split("/")[-1],
                        "object": "model",
                        "created": 1677649553,
                        "owned_by": "google",
                        "permission": []
                    })
        except Exception as e:
            utils.log(f"Error fetching Gemini models: {e}")

        # 2. Fetch OpenAI Models
        if config.OPENAI_API_KEY and config.OPENAI_BASE_URL:
            try:
                OPENAI_MODELS_URL = f"{config.OPENAI_BASE_URL}/models"
                headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

                async with session.get(OPENAI_MODELS_URL, headers=headers) as response:
                    response.raise_for_status()
                    openai_models_data = await response.json()

                for model in openai_models_data.get("data", []):
                    openai_models_list.append({
                        "id": model.get("id"),
                        "object": "model",
                        "created": model.get("created", 1677649553),
                        "owned_by": model.get("owned_by", "openai-compatible"),
                        "permission": []
                    })
            except Exception as e:
                utils.log(f"Error fetching OpenAI models: {e}")
        
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
        return jsonify({"error": f"Error fetching models: {e}"}), 500
