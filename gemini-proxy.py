import os
import requests
from flask import Flask, request, jsonify, Response
import time
import json
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
import base64
import re

app = Flask(__name__)
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable not set")

UPSTREAM_URL = os.getenv("UPSTREAM_URL")
if not UPSTREAM_URL:
    raise ValueError("UPSTREAM_URL environment variable not set")


cached_models_response = None
model_info_cache = {}
TOKEN_ESTIMATE_SAFETY_MARGIN = 0.95  # Use 95% of the model's capacity


# --- Helper Functions for Multimodal Support ---

def _process_image_url(image_url: dict) -> dict | None:
    """
    Processes an OpenAI image_url object and converts it to a Gemini inline_data part.
    Supports both web URLs and Base64 data URIs.
    """
    url = image_url.get("url")
    if not url:
        return None

    try:
        if url.startswith("data:"):
            # Handle Base64 data URI
            match = re.match(r"data:(image/.+);base64,(.+)", url)
            if not match:
                print(f"Warning: Could not parse data URI.")
                return None
            mime_type, base64_data = match.groups()
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
        else:
            # Handle web URL
            print(f"Downloading image from URL: {url}")
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            mime_type = response.headers.get("Content-Type", "image/jpeg")
            base64_data = base64.b64encode(response.content).decode('utf-8')
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
    except Exception as e:
        print(f"Error processing image URL {url}: {e}")
        return None


# --- Helper Functions for Token Management ---

def get_model_input_limit(model_name: str) -> int:
    """
    Fetches the input token limit for a given model from the Gemini API and caches it.
    """
    if model_name in model_info_cache:
        return model_info_cache[model_name].get("inputTokenLimit", 8192)  # Default to 8k if not found

    try:
        print(f"Cache miss for {model_name}. Fetching model details from API...")
        GEMINI_MODEL_INFO_URL = f"{UPSTREAM_URL}/v1beta/models/{model_name}"
        params = {"key": API_KEY}
        response = requests.get(GEMINI_MODEL_INFO_URL, params=params)
        response.raise_for_status()
        model_info = response.json()
        model_info_cache[model_name] = model_info
        return model_info.get("inputTokenLimit", 8192)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching model details for {model_name}: {e}. Using default limit of 8192.")
        return 8192  # Return a safe default on error


def estimate_token_count(contents: list) -> int:
    """
    Estimates the token count of the 'contents' list using a character-based heuristic.
    Approximation: 4 characters per token.
    """
    total_chars = 0
    for item in contents:
        for part in item.get("parts", []):
            if "text" in part:
                total_chars += len(part.get("text", ""))
    return total_chars // 4


def truncate_contents(contents: list, limit: int) -> list:
    """
    Truncates the 'contents' list by removing older messages (but keeping the first one)
    until the estimated token count is within the specified limit.
    """
    estimated_tokens = estimate_token_count(contents)
    if estimated_tokens <= limit:
        return contents

    print(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")

    # Keep the first message (often a system prompt) and the most recent ones.
    # We will remove messages from the second position (index 1).
    truncated_contents = contents.copy()
    while estimate_token_count(truncated_contents) > limit and len(truncated_contents) > 1:
        # Remove the oldest message after the initial system/user prompt
        truncated_contents.pop(1)

    final_tokens = estimate_token_count(truncated_contents)
    print(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents


# --- API Endpoints ---
@app.route('/', methods=['GET'])
def index():
    """
    Serves a simple documentation page in English.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gemini to OpenAI Proxy</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; padding: 2em; max-width: 800px; margin: auto; color: #333; background-color: #f9f9f9; }
            h1, h2 { color: #1a73e8; }
            code { background-color: #e0e0e0; padding: 2px 6px; border-radius: 4px; font-family: "SF Mono", "Fira Code", "Source Code Pro", monospace; }
            pre { background-color: #e0e0e0; padding: 1em; border-radius: 4px; overflow-x: auto; }
            .container { background-color: #fff; padding: 2em; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
            .footer { margin-top: 2em; text-align: center; font-size: 0.9em; color: #777; }
            li { margin-bottom: 0.5em; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Gemini to OpenAI Proxy</h1>
            <p>This is a lightweight proxy server that translates requests from an OpenAI-compatible client (like JetBrains AI Assistant) to Google's Gemini API.</p>

            <h2>What It Does</h2>
            <ul>
                <li>Accepts requests on OpenAI-like endpoints: <code>/v1beta/openai/chat/completions</code> and <code>/v1beta/openai/models</code>.</li>
                <li>Transforms the request format from OpenAI's structure to Gemini's structure.</li>
                <li>Handles streaming responses for chat completions.</li>
                <li>Manages basic conversation history truncation to fit within the model's token limits.</li>
                <li>Caches model lists to reduce upstream API calls.</li>
                <li>Supports multimodal requests (text and images).</li>
            </ul>

            <h2>How to Use</h2>

            <h3>1. Setup and Run</h3>
            <p>Before running the server, you need to set two environment variables:</p>
            <pre><code>export API_KEY="YOUR_GEMINI_API_KEY"
export UPSTREAM_URL="https://generativelanguage.googleapis.com"</code></pre>
            <p>Then, run the server:</p>
            <pre><code>python gemini-proxy.py</code></pre>
            <p>The server will start on <code>http://0.0.0.0:8080</code> by default.</p>

            <h3>2. Configure JetBrains AI Assistant</h3>
            <p>To use this proxy with JetBrains IDEs:</p>
            <ol>
                <li>Open AI Assistant settings (<code>Settings</code> > <code>Tools</code> > <code>AI Assistant</code>).</li>
                <li>Select the "Custom" service.</li>
                <li>Set the <b>Server URL</b> to: <code>http://&lt;your-server-ip-or-localhost&gt;:8080/v1beta/openai</code></li>
                <li>The model list will be fetched automatically. You can leave it as default or choose a specific one.</li>
            </ol>
            <p><b>Note:</b> The path must end with <code>/v1beta/openai</code> because the IDE will append <code>/chat/completions</code> or <code>/models</code> to it.</p>

            <h2>Available Endpoints</h2>
            <ul>
                <li><code>GET /</code>: This documentation page.</li>
                <li><code>GET /v1beta/openai/models</code>: Lists available Gemini models in OpenAI format.</li>
                <li><code>POST /v1beta/openai/chat/completions</code>: The main endpoint for chat completions. Supports streaming.</li>
            </ul>

            <div class="footer">
                <p>Proxy server is running and ready to serve requests.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


@app.route('/v1beta/openai/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completion requests using the 'requests' library with streaming.
    """
    try:
        openai_request = request.json
        print(f"Incoming JetBrains AI Assist Request: {pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])
        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')

        # Transform messages to Gemini format, merging consecutive messages of the same role
        gemini_contents = []
        if messages:
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
                            image_part = _process_image_url(part.get("image_url", {}))
                            if image_part:
                                gemini_parts.append(image_part)

                    # Combine all text parts into a single text part for Gemini
                    if text_parts:
                        gemini_parts.insert(0, {"text": "\n".join(text_parts)})

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
        token_limit = get_model_input_limit(COMPLETION_MODEL)
        safe_limit = int(token_limit * TOKEN_ESTIMATE_SAFETY_MARGIN)

        # Truncate messages if they exceed the safe limit
        original_message_count = len(gemini_contents)
        truncated_gemini_contents = truncate_contents(gemini_contents, safe_limit)
        if len(truncated_gemini_contents) < original_message_count:
            print(f"Truncated conversation from {original_message_count} to {len(truncated_gemini_contents)} messages.")

        request_data = {
            "contents": truncated_gemini_contents
        }

        GEMINI_STREAMING_URL = f"{UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"

        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': API_KEY
        }

        print(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
        print(f"Outgoing Gemini Request Data: {pretty_json(request_data)}")

        # Use a generator function to handle the streaming response
        def generate():
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

                # Yield a single error chunk to the client
                error_chunk = {
                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": COMPLETION_MODEL,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": error_message},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

                # Yield the final chunk to signal the end
                final_chunk = {
                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": COMPLETION_MODEL,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Process the successful streaming response
            buffer = ""
            for chunk in response.iter_lines(decode_unicode=True):
                if chunk:
                    buffer += chunk
                    try:
                        clean_buffer = buffer.strip(',[] \n')
                        if not clean_buffer:
                            continue

                        if clean_buffer.endswith('}') or clean_buffer.endswith(']'):
                            try:
                                json_data = json.loads(clean_buffer)
                                text_part = json_data['candidates'][0]['content']['parts'][0]['text']

                                chunk_response = {
                                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": COMPLETION_MODEL,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": text_part},
                                        "finish_reason": None
                                    }]
                                }
                                print(f"Formatted Proxy Response Chunk: {pretty_json(chunk_response)}")
                                yield f"data: {json.dumps(chunk_response)}\n\n"
                                buffer = ""
                            except (json.JSONDecodeError, KeyError, IndexError):
                                # Incomplete JSON or unexpected structure, continue buffering
                                continue
                    except Exception as e:
                        print(f"Error processing chunk: {e}")
                        continue

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
            print(f"Final Proxy Response Chunk: {pretty_json(final_chunk)}")
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
@app.route('/v1beta/openai/models', methods=['GET'])
def list_models():
    """
    Fetches the list of available models from the Gemini API, caches the response,
    and formats it for the JetBrains AI Assist/OpenAI API.
    """
    global cached_models_response

    try:
        if cached_models_response:
            return jsonify(cached_models_response)

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
        cached_models_response = openai_response
        return jsonify(openai_response)

    except requests.exceptions.RequestException as e:
        error_response = {"error": f"Error fetching models from Gemini API: {e}"}
        return jsonify(error_response), 500
    except Exception as e:
        error_response = {"error": f"Internal server error: {e}"}
        return jsonify(error_response), 500


def pretty_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    print("Starting proxy server on http://0.0.0.0:8080...")
    app.run(host='0.0.0.0', port=8080)