"""
 BelVG LLC.

 NOTICE OF LICENSE

 This source file is subject to the EULA
 that is bundled with this package in the file LICENSE.txt.
 It is also available through the world-wide-web at this URL:
 https://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

 *******************************************************************
 @category   BelVG
 @author     Oleg Semenov
 @copyright  Copyright (c) BelVG LLC. (http://www.belvg.com)
 @license    http://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

"""
import os
import requests
from flask import Flask, request, jsonify, Response, redirect, url_for, render_template
import time
import json
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
from dotenv import load_dotenv, set_key

import mcp_handler
import utils


app = Flask(__name__)

# Load environment variables from .env file at startup
load_dotenv()

# Load configurations from external modules
mcp_handler.load_mcp_config()
utils.load_prompt_config()

# --- Global Configuration ---
API_KEY = os.getenv("API_KEY")
UPSTREAM_URL = os.getenv("UPSTREAM_URL")
if not UPSTREAM_URL:
    raise ValueError("UPSTREAM_URL environment variable not set")

# --- API Endpoints ---
@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    """
    Sets the API_KEY from a web form and saves it to the .env file for persistence.
    """
    global API_KEY
    new_key = request.form.get('api_key')
    if new_key:
        # Update the key in the current session
        API_KEY = new_key

        # Save the key to the .env file for persistence across restarts
        set_key('.env', 'API_KEY', new_key)
        utils.log("API Key has been updated via web interface and saved to .env file.")

        # Clear model cache if key changes
        utils.cached_models_response = None
        utils.model_info_cache.clear()
        utils.log("Caches cleared due to API key change.")
    return redirect(url_for('index', _anchor='configuration'))


@app.route('/set_logging', methods=['POST'])
def set_logging():
    """Enables or disables verbose logging."""
    logging_enabled = request.form.get('verbose_logging') == 'on'
    utils.set_verbose_logging(logging_enabled)
    return redirect(url_for('index', _anchor='configuration'))


@app.route('/set_mcp_config', methods=['POST'])
def set_mcp_config():
    """Saves MCP tool configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('mcp_config')
    if config_str:
        try:
            # Validate JSON before writing
            json.loads(config_str.strip())
            with open(mcp_handler.MCP_CONFIG_FILE, 'w') as f:
                f.write(config_str.strip())
            utils.log(f"MCP config updated and saved to {mcp_handler.MCP_CONFIG_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in MCP config: {e}")
            # Don't reload config if JSON is invalid
            return redirect(url_for('index', _anchor='mcp'))
    elif os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        # Handle empty submission: clear the config
        os.remove(mcp_handler.MCP_CONFIG_FILE)
        utils.log("MCP config cleared.")

    mcp_handler.load_mcp_config()  # Reload config and fetch new schemas
    return redirect(url_for('index', _anchor='mcp'))

@app.route('/set_prompt_config', methods=['POST'])
def set_prompt_config():
    """Saves prompt override configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('prompt_overrides')
    if config_str:
        try:
            # Validate JSON before writing
            json.loads(config_str.strip())
            with open(utils.PROMPT_OVERRIDES_FILE, 'w') as f:
                f.write(config_str.strip())
            utils.log(f"Prompt overrides updated and saved to {utils.PROMPT_OVERRIDES_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in prompt overrides: {e}")
            # Don't reload config if JSON is invalid
            return redirect(url_for('index', _anchor='prompts'))
    elif os.path.exists(utils.PROMPT_OVERRIDES_FILE):
        # Handle empty submission: clear the config
        os.remove(utils.PROMPT_OVERRIDES_FILE)
        utils.log("Prompt overrides config cleared.")

    utils.load_prompt_config()
    return redirect(url_for('index', _anchor='prompts'))

@app.route('/', methods=['GET'])
def index():
    """
    Serves a simple documentation page in English.
    """
    api_key_status = "Set" if API_KEY else "Not Set"

    current_mcp_config_str = ""
    if os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        with open(mcp_handler.MCP_CONFIG_FILE, 'r') as f:
            current_mcp_config_str = f.read()

    current_prompt_overrides_str = ""
    if os.path.exists(utils.PROMPT_OVERRIDES_FILE):
        with open(utils.PROMPT_OVERRIDES_FILE, 'r') as f:
            current_prompt_overrides_str = f.read()

    default_prompt_overrides = {
      "default_chat": {
        "triggers": ["You are a JetBrains AI Assistant for code development."],
        "overrides": {
          "Follow the user's requirements carefully & to the letter.": ""
        }
      },
      "commit_message": {
        "triggers": ["[Diff]"],
        "overrides": {
          "Write a short and professional commit message for the following changes:": "Write a short and professional commit message for the following changes:"
        }
      }
    }

    default_mcp_config = {
      "mcpServers": {
        "youtrack": {
          "command": "docker",
          "args": [
            "run", "--rm", "-i",
            "-e", "YOUTRACK_API_TOKEN",
            "-e", "YOUTRACK_URL",
            "tonyzorin/youtrack-mcp:latest"
          ],
          "env": {
            "YOUTRACK_API_TOKEN": "perm-your-token-here",
            "YOUTRACK_URL": "https://youtrack.example.com/"
          }
        }
      }
    }

    return render_template(
        'index.html',
        API_KEY=API_KEY,
        api_key_status=api_key_status,
        current_mcp_config_str=current_mcp_config_str,
        default_mcp_config_json=utils.pretty_json(default_mcp_config),
        current_prompt_overrides_str=current_prompt_overrides_str,
        default_prompt_overrides_json=utils.pretty_json(default_prompt_overrides),
        verbose_logging_status=utils.VERBOSE_LOGGING
    )

@app.route('/favicon.ico')
def favicon():
    """Serves the favicon for the web interface."""
    favicon_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⚙️</text></svg>'
    return Response(favicon_svg, mimetype='image/svg+xml')


@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completion requests, including tool calls for MCP servers.
    """
    if not API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        openai_request = request.json
        utils.log(f"Incoming Request: {utils.pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])

        # --- Prompt Engineering & Tool Control ---
        force_tools_enabled = True  # None: default, True: force, False: disable

        if messages:
            active_overrides = {}
            active_profile_name = None
            # Identify prompt profile by checking for triggers in the combined text of all messages
            full_prompt_text = " ".join(
                [m.get('content') for m in messages if isinstance(m.get('content'), str)]
            )

            if utils.prompt_overrides:
                for profile_name, profile_data in utils.prompt_overrides.items():
                    if isinstance(profile_data, dict):
                        for trigger in profile_data.get('triggers', []):
                            if trigger in full_prompt_text:
                                active_profile_name = profile_name
                                active_overrides = profile_data.get('overrides', {})
                                # If it's a commit message profile, do not send tools
                                if active_profile_name == "commit_message":
                                    force_tools_enabled = False
                                utils.log(f"Prompt profile matched: '{profile_name}'")
                                break
                        if active_overrides:
                            break

            # Process all messages: apply overrides and check for tool keywords in the last message
            for i, message in enumerate(messages):
                content = message.get('content')
                if isinstance(content, str):
                    # Apply overrides from the matched profile
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    message['content'] = content
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
                            image_part = utils._process_image_url(part.get("image_url", {}))
                            if image_part:
                                gemini_parts.append(image_part)

                    # Combine all text parts into a single text part for Gemini
                    if text_parts:
                        gemini_parts.insert(0, {"text": "\n".join(text_parts)})

                if gemini_parts:
                    mapped_messages.append({"role": role, "parts": gemini_parts})

            # Prepare system instruction to be sent via systemInstruction if tools are configured
            if mcp_handler.mcp_function_declarations:
                system_instruction_text = (
                    "You are a helpful assistant with access to tools. When a user's request requires using a tool, "
                    "you MUST use the functionCall feature to invoke the appropriate tool. Do not simulate tool calls "
                    "or generate tool output as plain text. Always use the structured functionCall mechanism."
                )

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
        token_limit = utils.get_model_input_limit(COMPLETION_MODEL, API_KEY, UPSTREAM_URL)
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

                # Add tool declarations if MCP tools are configured and enabled for this request
                tools = mcp_handler.create_tool_declarations(full_prompt_text)
                if tools and force_tools_enabled:
                    request_data["tools"] = tools
                    request_data["tool_config"] = {
                        "function_calling_config": {
                            "mode": "AUTO"
                        }
                    }

                GEMINI_STREAMING_URL = f"{UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"
                headers = {
                    'Content-Type': 'application/json',
                    'X-goog-api-key': API_KEY
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
                        # Find the start of a JSON object
                        start_index = buffer.find('{')
                        if start_index == -1:
                            # No start of object in buffer, wait for more data
                            # prevent unbounded growth on malformed input
                            if len(buffer) > 65536:
                                buffer = buffer[-32768:]
                            break

                        # Drop any non-JSON prefix (SSE noise, commas, brackets, newlines)
                        if start_index > 0:
                            buffer = buffer[start_index:]

                        # Try to decode a full JSON object from the current buffer
                        try:
                            json_data, end_index = decoder.raw_decode(buffer)
                        except json.JSONDecodeError:
                            # Need more data
                            break

                        # Advance the buffer to the remainder after the parsed object
                        buffer = buffer[end_index:]

                        # Process the valid JSON object
                        parts = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])

                        # Handle metadata-only chunks gracefully
                        if not parts and 'usageMetadata' in json_data:
                            pass
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

                if not tool_calls:
                    # No tool calls, conversation is finished
                    break

                # --- Tool Call Execution ---
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
                    # Try to parse tool output as JSON for structured responses; ensure response is an object
                    response_payload = None
                    if isinstance(output, str):
                        try:
                            parsed_output = json.loads(output)
                            # Ensure object; wrap non-dicts
                            if isinstance(parsed_output, dict):
                                response_payload = parsed_output
                            else:
                                response_payload = {"content": parsed_output}
                        except json.JSONDecodeError:
                            # Not JSON -> treat as plain text
                            response_payload = {"text": output}
                    else:
                        # Non-string output
                        if isinstance(output, dict):
                            response_payload = output
                        elif output is None:
                            response_payload = {"text": ""}
                        else:
                            response_payload = {"content": output}

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
                # Loop will continue to call Gemini with tool results

            # Send the final chunk after the stream is finished
            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            utils.log(f"Final Proxy Response Chunk: {utils.pretty_json(final_chunk)}")
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        error_message = f"An error occurred: {str(e)}"
        print(f"An error occurred during chat completion: {error_message}")

        # Формируем стандартный ответ с ошибкой
        error_response = {
            "error": {
                "message": error_message,
                "type": "server_error",
                "code": "500"
            }
        }
        return jsonify(error_response), 500

# The /v1/models endpoint remains the same
@app.route('/v1/models', methods=['GET'])
def list_models():
    """
    Fetches the list of available models from the Gemini API, caches the response,
    and formats it for the JetBrains AI Assist/OpenAI API.
    """
    if not API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401

    try:
        if utils.cached_models_response:
            return jsonify(utils.cached_models_response)

        params = {"key": API_KEY}
        GEMINI_MODELS_URL = f"{UPSTREAM_URL}/v1beta/models"
        response = requests.get(GEMINI_MODELS_URL, params=params)
        response.raise_for_status()

        gemini_models_data = response.json()

        # Transform the Gemini model list to the OpenAI/JetBrains AI Assist format
        openai_models_list = []
        for model in gemini_models_data.get("models", []):
            # Only include models that support content generation
            if "generateContent" in model.get("supportedGenerationMethods", []):
                openai_models_list.append({
                    "id": model["name"].split("/")[-1],
                    "object": "model",
                    "created": 1677649553,
                    "owned_by": "google",
                    "permission": []
                })

        openai_response = {
            "object": "list",
            "data": openai_models_list
        }

        # Cache the successful response
        utils.cached_models_response = openai_response
        return jsonify(openai_response)

    except requests.exceptions.RequestException as e:
        error_response = {"error": f"Error fetching models from Gemini API: {e}"}
        return jsonify(error_response), 500
    except Exception as e:
        error_response = {"error": f"Internal server error: {e}"}
        return jsonify(error_response), 500

if __name__ == '__main__':
    print("Starting proxy server on http://0.0.0.0:8080...")
    app.run(host='0.0.0.0', port=8080)