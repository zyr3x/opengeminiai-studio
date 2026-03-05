import httpx
import asyncio
import fnmatch
import json
import os
import time
import traceback
from flask import Blueprint, request, jsonify, Response
from httpx import HTTPStatusError, RequestError

from app.config import config
from app.utils.flask import optimization
from app.utils.core import mcp_handler, tools as utils
from app.utils.core import tool_config_utils
from app.utils.flask.optimization import record_token_usage
from app.utils.core.optimization_utils import can_execute_parallel
from app.utils.core.ai_provider_manager import ai_provider_manager

import traceback
from app.utils.core import file_processing_utils
proxy_bp = Blueprint('proxy', __name__)
@proxy_bp.route('/chat/completions', methods=['POST'])
async def chat_completions():
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        openai_request = request.json
        utils.debug(f"Incoming Request: {utils.pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])
        
        disable_mcp_tools = False
        explicit_mcp_tools = openai_request.get('mcp_tools')
        if explicit_mcp_tools and not isinstance(explicit_mcp_tools, list):
             explicit_mcp_tools = None

        enable_native_tools = False
        project_system_context_text = None
        profile_selected_mcp_tools = []

        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            disable_mcp_tools = True
            profile_selected_mcp_tools = []

        project_context_tools_requested = False
        project_context_root = None
        processed_messages = []
        processed_code_paths = set()

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

            for message in messages:
                content = message.get('content')

                if isinstance(content, str):
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    processed_content, project_path_found, new_system_context = file_processing_utils.process_message_for_paths(
                        content, processed_code_paths
                    )

                    message['content'] = processed_content

                    if new_system_context:
                        project_system_context_text = new_system_context

                    if not disable_mcp_tools:
                        if project_path_found and config.AGENT_INTELLIGENCE_ENABLED:
                            project_context_tools_requested = True
                            if isinstance(project_path_found, str):
                                project_context_root = project_path_found

                processed_messages.append(message)

            messages = processed_messages
        else:
            full_prompt_text = ""

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        
        # Determine provider: Check registration first to catch custom providers serving Gemini models
        explicit_provider = None
        if '::' in COMPLETION_MODEL:
            parts = COMPLETION_MODEL.split('::', 1)
            possible_provider = ai_provider_manager.get_provider_by_name(parts[0])
            if possible_provider:
                explicit_provider = possible_provider
                COMPLETION_MODEL = parts[1]
            elif parts[0] == 'Google':
                COMPLETION_MODEL = parts[1]

        if explicit_provider:
            provider = 'openai'
        elif ai_provider_manager.is_model_registered(COMPLETION_MODEL):
            provider = 'openai'
        else:
            provider = utils.get_provider_for_model(COMPLETION_MODEL)

        if provider == 'openai':
            # Resolve provider credentials dynamically
            provider_conf = explicit_provider if explicit_provider else ai_provider_manager.get_provider_for_model(COMPLETION_MODEL)
            
            # Fallback values from config if provider lookup fails or returns partial data
            base_url = provider_conf.get('base_url') if provider_conf else config.OPENAI_BASE_URL
            api_key = provider_conf.get('api_key') if provider_conf else config.OPENAI_API_KEY
            
            stream = openai_request.get('stream', False)
            
            async def generate_openai():
                current_messages = messages.copy()
                # Inject system prompt if needed
                if project_system_context_text:
                    current_messages.insert(0, {"role": "system", "content": project_system_context_text})

                while True:
                    request_data = {
                        "model": COMPLETION_MODEL,
                        "messages": current_messages,
                        "stream": True,
                        "temperature": 0.7
                    }

                    # Tools setup for OpenAI
                    openai_tools = []
                    builtin_tool_names = list(mcp_handler.BUILTIN_FUNCTIONS.keys())
                    if not disable_mcp_tools:
                        if explicit_mcp_tools:
                            openai_tools.extend(mcp_handler.get_openai_compatible_tools(explicit_mcp_tools))
                        elif project_context_tools_requested:
                            openai_tools.extend(mcp_handler.get_openai_compatible_tools(builtin_tool_names))
                        elif profile_selected_mcp_tools:
                            openai_tools.extend(mcp_handler.get_openai_compatible_tools(profile_selected_mcp_tools))
                        else:
                            openai_tools.extend(mcp_handler.get_openai_compatible_tools(builtin_tool_names))

                    if openai_tools:
                        request_data["tools"] = openai_tools
                        request_data["tool_choice"] = "auto"

                    utils.debug(f"Outgoing OpenRouter Request Data: {utils.pretty_json(request_data)}")

                    tool_calls = []
                    current_tool_call = None
                    full_response_text = ""
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    try:
                        async with httpx.AsyncClient(timeout=300.0) as client:
                            async with client.stream(
                                "POST", f"{base_url}/chat/completions",
                                headers=headers, json=request_data
                            ) as response:
                                response.raise_for_status()
                                
                                async for line in response.aiter_lines():
                                    if not line or not line.startswith('data: '): continue
                                    if line == 'data: [DONE]': break
                                    
                                    
                                    try:
                                        chunk = json.loads(line[6:])
                                        
                                        if 'usage' in chunk and chunk['usage']:
                                            usage = chunk['usage']
                                            record_token_usage(api_key, COMPLETION_MODEL, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))

                                        choices = chunk.get('choices', [])
                                        if not choices: continue
                                        
                                        delta = choices[0].get('delta', {})
                                        finish_reason = choices[0].get('finish_reason')

                                        if 'content' in delta and delta['content']:
                                            full_response_text += delta['content']
                                            yield f"data: {json.dumps(chunk)}\n\n"
                                        elif finish_reason and finish_reason != 'tool_calls':
                                            yield f"data: {json.dumps(chunk)}\n\n"

                                        if 'tool_calls' in delta:
                                            for tc in delta['tool_calls']:
                                                if tc.get('id'):
                                                    if current_tool_call: tool_calls.append(current_tool_call)
                                                    current_tool_call = {'id': tc['id'], 'function': {'name': tc['function'].get('name', ''), 'arguments': tc['function'].get('arguments', '')}, 'type': 'function'}
                                                elif current_tool_call:
                                                    if 'name' in tc['function']: current_tool_call['function']['name'] += tc['function']['name']
                                                    if 'arguments' in tc['function']: current_tool_call['function']['arguments'] += tc['function']['arguments']
                                    except json.JSONDecodeError:
                                        continue

                    except Exception as e:
                        err_msg = f"OpenAI Provider Error ({base_url}): {e}"
                        utils.log(err_msg)
                        error_chunk = {"id": f"chatcmpl-{os.urandom(12).hex()}", "object": "chat.completion.chunk", "created": int(time.time()), "model": COMPLETION_MODEL, "choices": [{"index": 0, "delta": {"content": err_msg}, "finish_reason": "stop"}]}
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    if current_tool_call:
                        tool_calls.append(current_tool_call)

                    if not tool_calls:
                        yield "data: [DONE]\n\n"
                        break

                    # Process tool calls
                    current_messages.append({"role": "assistant", "content": full_response_text, "tool_calls": tool_calls})
                    for tool_call in tool_calls:
                        func_name = tool_call['function']['name']
                        try:
                            func_args = json.loads(tool_call['function']['arguments'])
                        except:
                            func_args = {}

                        utils.log(f"Executing tool: {func_name}")
                        tool_result = await asyncio.to_thread(mcp_handler.execute_mcp_tool, func_name, func_args, project_context_root)
                        current_messages.append({"role": "tool", "tool_call_id": tool_call['id'], "name": func_name, "content": str(tool_result)})

            if stream:
                from app.utils.core.streaming import async_to_sync_generator
                return Response(async_to_sync_generator(generate_openai()), mimetype='text/event-stream')
            else:
                # Non-streaming OpenAI: collect all content
                full_content = ""
                last_chunk = None
                it = generate_openai().__aiter__()
                while True:
                    try:
                        chunk_str = await it.__anext__()
                        if chunk_str.startswith('data: '):
                            if chunk_str == 'data: [DONE]\n\n': break
                            chunk_data = json.loads(chunk_str[6:-2])
                            last_chunk = chunk_data
                            delta = chunk_data['choices'][0]['delta']
                            if 'content' in delta:
                                full_content += delta['content']
                    except StopAsyncIteration:
                        break
                
                if last_chunk:
                    # Construct non-streaming response
                    openai_response = {
                        "id": last_chunk.get("id"),
                        "object": "chat.completion",
                        "created": last_chunk.get("created"),
                        "model": COMPLETION_MODEL,
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": full_content},
                            "finish_reason": "stop"
                        }],
                        "usage": last_chunk.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                    }
                    return jsonify(openai_response)
                return jsonify({"error": "No response from upstream"}), 500

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

        token_limit = await utils.get_model_input_limit(COMPLETION_MODEL, config.API_KEY, config.UPSTREAM_URL)
        safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)
        stream = openai_request.get('stream', False)
        final_usage_metadata = {}

        async def generate():
            nonlocal final_usage_metadata
            current_contents = gemini_contents.copy()

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
                if not disable_mcp_tools:
                    if explicit_mcp_tools:
                        mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(explicit_mcp_tools)
                        utils.log(f"Using explicit MCP tools from request: {explicit_mcp_tools}")
                    elif project_context_tools_requested:
                        mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(builtin_tool_names)
                        utils.log(f"Project context activated via project_path=. Forcing use of built-in tools: {builtin_tool_names}")
                    elif profile_selected_mcp_tools:
                        mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(profile_selected_mcp_tools)
                        utils.log(f"Using MCP tools defined by prompt override profile: {profile_selected_mcp_tools}")
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
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        async with client.stream(
                            "POST",
                            GEMINI_STREAMING_URL,
                            headers=headers,
                            json=request_data
                        ) as response:
                            response.raise_for_status()

                            buffer = ""
                            tool_calls = []
                            model_response_parts = []
                            decoder = json.JSONDecoder()

                            async for chunk in response.aiter_text():
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

                                        candidates = json_data.get('candidates', [{}])
                                        if not candidates: continue
                                        
                                        parts = candidates[0].get('content', {}).get('parts', [])

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
                except Exception as e:
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

                    results = await optimization.execute_tools_parallel_async(parallel_calls, project_context_root)

                    for tool_call_data, output in results:
                        function_name = tool_call_data['name']

                        from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                        if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                            output = await utils.summarize_with_aux_model(output, function_name)

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

                        output = await asyncio.to_thread(mcp_handler.execute_mcp_tool, function_name, tool_args, project_context_root)

                        from app.utils.core.optimization_utils import estimate_tokens, MAX_TOOL_OUTPUT_TOKENS
                        if project_context_root and config.AGENT_AUX_MODEL_ENABLED and isinstance(output, str) and estimate_tokens(output) > MAX_TOOL_OUTPUT_TOKENS:
                            output = await utils.summarize_with_aux_model(output, function_name)

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

        if stream:
            from app.utils.core.streaming import async_to_sync_generator
            return Response(async_to_sync_generator(generate()), mimetype='text/event-stream')
        else:
            # Non-streaming Gemini: collect chunks
            full_content = ""
            last_chunk = None
            it = generate().__aiter__()
            while True:
                try:
                    chunk_str = await it.__anext__()
                    if chunk_str.startswith('data: '):
                        if chunk_str == 'data: [DONE]\n\n': break
                        chunk_data = json.loads(chunk_str[6:-2])
                        last_chunk = chunk_data
                        delta = chunk_data['choices'][0]['delta']
                        if 'content' in delta:
                            full_content += delta['content']
                except StopAsyncIteration:
                    break
            
            if last_chunk:
                input_tokens = final_usage_metadata.get('promptTokenCount', 0)
                output_tokens = final_usage_metadata.get('candidatesTokenCount', 0)
                
                openai_response = {
                    "id": last_chunk.get("id"),
                    "object": "chat.completion",
                    "created": last_chunk.get("created"),
                    "model": COMPLETION_MODEL,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": full_content},
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens
                    }
                }
                return jsonify(openai_response)
            return jsonify({"error": "No response from Gemini upstream"}), 500

    except Exception as e:
        utils.log(f"An error occurred during chat completion: {e}\n{traceback.format_exc()}")
        error_message = f"An error occurred: {str(e)}"
        error_response = {"error": {"message": error_message, "type": "server_error", "code": "500"}}
        return jsonify(error_response), 500
@proxy_bp.route('/models', methods=['GET'])
async def list_models():
    import fnmatch
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        if utils.cached_models_response:
            return jsonify(utils.cached_models_response)

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
                        model_id = model["name"].split("/")[-1]
                        openai_models_list.append({
                            "id": f"Google::{model_id}", "object": "model",
                            "created": 1677649553, "owned_by": "google", "permission": []
                        })
        except Exception as e:
            utils.log(f"Error fetching Gemini models: {e}")

        # 2. Fetch OpenAI/OpenRouter Models from ALL configured providers
        providers = ai_provider_manager.get_all_providers_data().get('providers', {}).values()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for provider in providers:
                if provider.get('api_key') and provider.get('base_url'):
                    try:
                        OPENAI_MODELS_URL = f"{provider['base_url']}/models"
                        headers = {
                            "Authorization": f"Bearer {provider['api_key']}",
                            "HTTP-Referer": "https://github.com/zyr3x/opengeminiai-studio",
                            "X-Title": "OpenGeminiAI Studio"
                        }
                        response = await client.get(OPENAI_MODELS_URL, headers=headers)
                        if response.status_code == 200:
                            openai_models_data = response.json()
                            for model in openai_models_data.get("data", []):
                                model_id = model.get("id")
                                provider_name = provider.get('name', 'unknown')
                                unique_model_id = f"{provider_name}::{model_id}" if provider_name != 'unknown' else model_id
                                
                                openai_models_list.append({
                                    "id": unique_model_id, "object": "model",
                                    "created": model.get("created", 1677649553),
                                    "owned_by": model.get("owned_by", "openai-compatible"),
                                    "permission": []
                                })
                                # Register model mapping to this provider
                                ai_provider_manager.register_model(model_id, provider.get('id'))
                                if unique_model_id != model_id:
                                    ai_provider_manager.register_model(unique_model_id, provider.get('id'))
                        else:
                            utils.log(f"Error fetching models from {provider.get('name')}: Status {response.status_code}")
                    except Exception as e:
                        utils.log(f"Error fetching models from {provider.get('name')}: {e}")

        # Deduplicate models (case-sensitive)
        seen_ids = set()
        unique_models_list = []
        for m in openai_models_list:
            if m['id'] not in seen_ids:
                unique_models_list.append(m)
                seen_ids.add(m['id'])
        openai_models_list = unique_models_list

        # Save model mappings to persist across restarts
        ai_provider_manager.save_providers()

        if config.ALLOWED_MODELS and '*' not in config.ALLOWED_MODELS:
            openai_models_list = [
                m for m in openai_models_list
                if any(fnmatch.fnmatch(m['id'].split('::', 1)[-1], pattern) for pattern in config.ALLOWED_MODELS)
            ]

        if config.IGNORED_MODELS:
            openai_models_list = [
                m for m in openai_models_list
                if not any(fnmatch.fnmatch(m['id'].split('::', 1)[-1], pattern) for pattern in config.IGNORED_MODELS)
            ]

        openai_response = {"object": "list", "data": openai_models_list}
        utils.cached_models_response = openai_response
        return jsonify(openai_response)

    except Exception as e:
        return jsonify({"error": f"Internal server error: {e}"}), 500
@proxy_bp.route('/system_prompts', methods=['GET'])
def list_system_prompts():
    try:
        from app.utils.core.prompt_loader import load_default_system_prompts
        current_system_prompts_str = ""
        if os.path.exists(utils.SYSTEM_PROMPTS_FILE):
            with open(utils.SYSTEM_PROMPTS_FILE, 'r') as f:
                current_system_prompts_str = f.read()

        default_system_prompts = load_default_system_prompts()
        system_prompt_profiles = default_system_prompts
        if current_system_prompts_str.strip():
            try:
                system_prompt_profiles = json.loads(current_system_prompts_str)
            except json.JSONDecodeError:
                pass
        return jsonify(system_prompt_profiles)
    except Exception as e:
        utils.log(f"Error fetching system prompts: {e}")
        return jsonify({"error": f"Internal server error: {e}"}), 500
