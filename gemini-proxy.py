import os
import requests
from flask import Flask, request, jsonify, Response
import time
import json
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException

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
                content = message.get("content", "")
                if content:  # Don't add empty messages
                    mapped_messages.append({"role": role, "parts": [{"text": content}]})

            # Merge consecutive messages with the same role, as Gemini requires alternating roles
            if mapped_messages:
                gemini_contents.append(mapped_messages[0])
                for i in range(1, len(mapped_messages)):
                    if mapped_messages[i]['role'] == gemini_contents[-1]['role']:
                        gemini_contents[-1]['parts'][0]['text'] += "\n\n" + mapped_messages[i]['parts'][0]['text']
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
                            except (json.JSONDecodeError, KeyError):
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
                    "created": int(time.time()),
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
    print("Starting proxy server on http://localhost:8080...")
    app.run(host='0.0.0.0', port=8080)