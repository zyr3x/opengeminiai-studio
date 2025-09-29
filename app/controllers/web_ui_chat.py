"""
Flask routes for the web UI, including the main page and direct chat API.
"""
import base64
import json
import requests
from flask import Blueprint, request, jsonify, Response
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException

from app.config import config
from app import mcp_handler
from app import utils

web_ui_chat_bp = Blueprint('web_ui_chat', __name__)

@web_ui_chat_bp.route('/chat_api', methods=['POST'])
def chat_api():
    """
    Handles direct chat requests from the web UI.
    """
    if not config.API_KEY:
        return jsonify({"error": "API key not configured."}), 401

    try:
        model = request.form.get('model', 'gemini-1.5-flash-latest')
        messages_json = request.form.get('messages', '[]')
        messages = json.loads(messages_json)
        attached_files = request.files.getlist('file')

        gemini_contents = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            content = message.get("content")
            if isinstance(content, str) and content:
                gemini_contents.append({"role": role, "parts": [{"text": content}]})

        if attached_files:
            if not gemini_contents or gemini_contents[-1]['role'] != 'user':
                gemini_contents.append({"role": "user", "parts": []})
            for attached_file in attached_files:
                file_base64 = base64.b64encode(attached_file.read()).decode('utf-8')
                gemini_contents[-1]['parts'].append({
                    "inline_data": {"mime_type": attached_file.mimetype, "data": file_base64}
                })

        full_prompt_text = " ".join(
            [p.get("text", "") for m in gemini_contents for p in m.get("parts", []) if "text" in p]
        )

        def generate():
            GEMINI_STREAMING_URL = f"{config.UPSTREAM_URL}/v1beta/models/{model}:streamGenerateContent"
            headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
            current_contents = gemini_contents.copy()

            while True:
                token_limit = utils.get_model_input_limit(model, config.API_KEY, config.UPSTREAM_URL)
                safe_limit = int(token_limit * utils.TOKEN_ESTIMATE_SAFETY_MARGIN)
                original_message_count = len(current_contents)
                current_contents = utils.truncate_contents(current_contents, safe_limit)
                if len(current_contents) < original_message_count:
                    utils.log(f"Truncated conversation from {original_message_count} to {len(current_contents)} messages.")

                request_data = {
                    "contents": current_contents,
                    "generationConfig": {"temperature": 0.7, "topP": 1.0, "maxOutputTokens": 2048}
                }
                tools = mcp_handler.create_tool_declarations(full_prompt_text)
                if tools:
                    request_data["tools"] = tools
                    request_data["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

                utils.log(f"Outgoing Direct Chat Request URL: {GEMINI_STREAMING_URL}")
                utils.log(f"Outgoing Direct Chat Request Data: {utils.pretty_json(request_data)}")

                try:
                    response = requests.post(
                        GEMINI_STREAMING_URL, headers=headers, json=request_data, stream=True, timeout=300
                    )
                    response.raise_for_status()
                except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                    yield f"ERROR: Error from upstream Gemini API: {e}"
                    return

                buffer, decoder, tool_calls, model_response_parts = "", json.JSONDecoder(), [], []
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
                            if not parts and 'usageMetadata' in json_data: continue

                            model_response_parts.extend(parts)
                            for part in parts:
                                if 'text' in part:
                                    yield part['text']
                                if 'functionCall' in part:
                                    tool_calls.append(part['functionCall'])
                        except json.JSONDecodeError:
                            if len(buffer) > 65536: buffer = buffer[-32768:]
                            break

                if not tool_calls: break

                utils.log(f"Detected tool calls: {utils.pretty_json(tool_calls)}")
                current_contents.append({"role": "model", "parts": model_response_parts})

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name = tool_call.get("name")
                    output = mcp_handler.execute_mcp_tool(function_name, tool_call.get("args"))
                    response_payload = None
                    if isinstance(output, str):
                        try:
                            parsed_output = json.loads(output)
                            response_payload = parsed_output if isinstance(parsed_output, dict) else {"content": parsed_output}
                        except json.JSONDecodeError:
                            response_payload = {"text": output}
                    else:
                        response_payload = output if isinstance(output, dict) else ({"text": ""} if output is None else {"content": output})

                    tool_response_parts.append({"functionResponse": {"name": function_name, "response": response_payload}})

                current_contents.append({"role": "tool", "parts": tool_response_parts})

        return Response(generate(), mimetype='text/plain')
    except Exception as e:
        print(f"An error occurred in chat API: {str(e)}")
        return jsonify({"error": f"An error occurred in chat API: {str(e)}"}), 500