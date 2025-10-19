"""
Flask routes for the OpenAI-compatible proxy endpoints.
"""
import json
import os
import time
import requests
from flask import Blueprint, request, jsonify, Response
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException

from app.config import config
from app import mcp_handler
from app import utils
from app import tool_config_utils
from app import file_processing_utils

proxy_bp = Blueprint('proxy', __name__)

@proxy_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completion requests, including tool calls for MCP servers.
    """
    if not config.API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        openai_request = request.json
        utils.log(f"Incoming Request: {utils.pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])

        # --- Prompt Engineering & Tool Control ---
        force_tools_enabled = True  # None: default, True: force, False: disable
        enable_native_tools = False
        profile_selected_mcp_tools = [] # to store tools explicitly selected by profile

        # Global setting to disable all MCP tools takes highest precedence
        if mcp_handler.disable_all_mcp_tools:
            utils.log("All MCP tools globally disabled via general settings.")
            force_tools_enabled = False
            profile_selected_mcp_tools = [] # Clear any profile-selected tools

        if messages:
            # Identify prompt profile by checking for triggers in the combined text of all messages
            full_prompt_text = " ".join(
                [m.get('content') for m in messages if isinstance(m.get('content'), str)]
            )

            # Apply Prompt Engineering & Tool Control Overrides
            override_config = tool_config_utils.get_prompt_override_config(full_prompt_text)
            active_overrides = override_config['active_overrides']

            # Apply profile flags (these might override initial global disable settings 
            # if the original flow allowed it, particularly for explicit tool selection)
            if override_config['disable_mcp_tools_by_profile']:
                force_tools_enabled = False

            if override_config['enable_native_tools_by_profile']:
                enable_native_tools = True

            if override_config['profile_selected_mcp_tools']:
                profile_selected_mcp_tools = override_config['profile_selected_mcp_tools']
                force_tools_enabled = True # Explicit selection overrides general disable

            # Process all messages: apply overrides
            for message in messages:
                content = message.get('content')
                if isinstance(content, str):
                    # Apply overrides from the matched profile
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    # --- Handle local file paths like image_path=... and pdf_path=... ---
                    message['content'] = file_processing_utils.process_message_for_paths(content)
        else:
            full_prompt_text = ""
        # --- End Prompt Engineering ---

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        system_instruction = None

        # Transform messages to Gemini format, merging consecutive messages of the same role
        gemini_contents = []
        if messages:
            # Separate system instruction from other messages
            if messages[0].get("role") == "system":
                system_instruction = {"parts": [{"text": messages[0].get("content", "")}]}
                messages = messages[1:]  # Remove system message from list

            # Map OpenAI roles to Gemini roles ('assistant' -> 'model', others -> 'user')
            mapped_messages = []
            for message in messages:
                role = "model" if message.get("role") == "assistant" else "user"
                content = message.get("content")

                gemini_parts = []
                # Content can be a string or a list of parts (for multimodal)
                if isinstance(content, str):
                    if content:  # Don't add empty messages
                        gemini_parts.append({"text": content})
                elif isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            # If there is preceding text, add it as a single part before the image
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

                    # Add any trailing text parts
                    if text_parts:
                        gemini_parts.append({"text": "\n".join(text_parts)})

                if gemini_parts:
                    mapped_messages.append({"role": role, "parts": gemini_parts})

            # Merge consecutive messages with the same role, as Gemini requires alternating roles
            if mapped_messages:
                gemini_contents.append(mapped_messages[0])
                for i in range(1, len(mapped_messages)):
                    if mapped_messages[i]['role'] == gemini_contents[-1]['role']:
                        # Append parts instead of just text to handle images correctly
                        gemini_contents[-1]['parts'].extend(mapped_messages[i]['parts'])
                    else:
                        gemini_contents.append(mapped_messages[i])

        # --- Token Management ---
        # Get the token limit for the requested model
        token_limit = utils.get_model_input_limit(COMPLETION_MODEL, config.API_KEY, config.UPSTREAM_URL)
        safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)

        # Use a generator function to handle the streaming response and tool calls
        def generate():
            current_contents = gemini_contents.copy()

            while True:  # Loop to handle sequential tool calls
                # Truncate messages before each call to ensure they fit within the token limit
                original_message_count = len(current_contents)
                current_contents = utils.truncate_contents(current_contents, safe_limit)
                if len(current_contents) < original_message_count:
                    utils.log(f"Truncated conversation from {original_message_count} to {len(current_contents)} messages to fit context window.")

                request_data = {
                    "contents": current_contents
                }
                if system_instruction:
                    request_data["systemInstruction"] = system_instruction

                # --- Tool Configuration ---
                final_tools = []
                mcp_declarations_to_use = None

                # Priority:
                # 1. Profile-defined selected tools (from prompt override)
                # 2. Context-aware tools (default, if force_tools_enabled)
                if profile_selected_mcp_tools:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations_from_list(profile_selected_mcp_tools)
                    utils.log(f"Using MCP tools defined by prompt override profile: {profile_selected_mcp_tools}")
                elif force_tools_enabled:
                    mcp_declarations_to_use = mcp_handler.create_tool_declarations(full_prompt_text)
                    utils.log(f"Using context-aware MCP tools (force_tools_enabled).")
                else:
                    utils.log(f"MCP Tools explicitly disabled or no tools selected.")

                if mcp_declarations_to_use:
                    final_tools.extend(mcp_declarations_to_use)

                # Add native Google tools if enabled
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

                utils.log(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
                utils.log(f"Outgoing Gemini Request Data: {utils.pretty_json(request_data)}")

                response = None
                try:
                    response = requests.post(
                        GEMINI_STREAMING_URL,
                        headers=headers,
                        json=request_data,
                        stream=True,
                        timeout=300
                    )
                    response.raise_for_status()
                except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                    error_message = f"Error from upstream Gemini API: {e}"
                    print(error_message)
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

                # Process the successful streaming response
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
                                    utils.log(f"Active Proxy Response Chunk: {utils.pretty_json(chunk_response)}")
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                        except json.JSONDecodeError:
                            if len(buffer) > 65536: buffer = buffer[-32768:]
                            break
                # If the model is silent after a tool call, construct a response from the tool's output
                # to avoid an empty message and ensure the user sees the result.
                is_after_tool_call = current_contents and current_contents[-1].get('role') == 'tool'
                has_text_in_model_response = any('text' in p for p in model_response_parts)

                if is_after_tool_call and not has_text_in_model_response and not tool_calls:
                    tool_parts_from_history = current_contents[-1].get('parts', [])
                    final_text = utils.format_tool_output_for_display(tool_parts_from_history)

                    if final_text:
                        model_response_parts = [{'text': final_text}]
                        # Stream the generated tool output to the client as an OpenAI chunk
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

                utils.log(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({
                    "role": "model",
                    "parts": model_response_parts
                })

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name = tool_call.get("name")
                    tool_args = tool_call.get("args")
                    output = mcp_handler.execute_mcp_tool(function_name, tool_args)

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

                current_contents.append({
                    "role": "tool",
                    "parts": tool_response_parts
                })

            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            utils.log(f"Final Proxy Response Chunk: {utils.pretty_json(final_chunk)}")
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        error_message = f"An error occurred: {str(e)}"
        print(f"An error occurred during chat completion: {error_message}")
        error_response = {"error": {"message": error_message, "type": "server_error", "code": "500"}}
        return jsonify(error_response), 500

@proxy_bp.route('/v1/models', methods=['GET'])
def list_models():
    """
    Fetches the list of available models from the Gemini API and caches the response.
    """
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
