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
if not API_KEY:
    raise ValueError("UPSTREAM_URL environment variable not set")


cached_models_response = None

# --- API Endpoints ---
@app.route('/v1beta/openai/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completion requests using the 'requests' library with streaming.
    """
    try:
        openai_request = request.json
        print(f"Incoming JetBrains AI Assist Request: {json.dumps(openai_request, indent=2)}")
        messages = openai_request.get('messages', [])
        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')

        # Consolidate all messages into a single user message
        combined_text = ""
        for message in messages:
            combined_text += f"{message.get('role')}: {message.get('content')}\n\n"

        request_data = {
            "contents": [
                {"role": "user", "parts": [{"text": combined_text}]}
            ]
        }

        GEMINI_STREAMING_URL = f"{UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"

        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': API_KEY
        }

        print(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
        print(f"Outgoing Gemini Request Data: {json.dumps(request_data, indent=2)}")

        # Use a generator function to handle the streaming response
        def generate():
            max_retries = 5
            initial_delay = 1.0  # seconds
            successful_response = None

            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        GEMINI_STREAMING_URL,
                        headers=headers,
                        json=request_data,
                        stream=True,
                        timeout=300  # Add a timeout to prevent hanging indefinitely
                    )
                    response.raise_for_status()  # Will raise HTTPError for 4xx/5xx responses
                    successful_response = response
                    break  # If successful, break out of the retry loop
                except HTTPError as e:
                    if e.response.status_code == 429:
                        delay = initial_delay * (2 ** attempt)
                        print(
                            f"Rate limit hit (429). Retrying in {delay:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        if attempt == max_retries - 1:
                            print(f"Max retries reached for 429 error. Failing after {max_retries} attempts.")
                            raise  # Re-raise the last 429 exception
                    else:
                        print(f"HTTPError (status {e.response.status_code}) not 429. Not retrying. Error: {e}")
                        raise  # Re-raise other HTTP errors immediately
                except (ConnectionError, Timeout, RequestException) as e:
                    # Catch network issues, timeouts, and general request exceptions
                    delay = initial_delay * (2 ** attempt)
                    print(
                        f"Request error: {e.__class__.__name__}: {e}. Retrying in {delay:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    if attempt == max_retries - 1:
                        print(f"Max retries reached for request error. Failing after {max_retries} attempts.")
                        raise

            if successful_response is None:
                # If we reach here, it means all retries failed and no successful response was obtained.
                print("Failed to obtain a successful streaming response after multiple retries.")
                raise RuntimeError("Failed to obtain a successful streaming response after multiple retries.")

            buffer = ""
            for chunk in successful_response.iter_lines(decode_unicode=True):
                if chunk:
                    buffer += chunk
                    try:
                        # The Gemini stream is an array of JSON objects.
                        # We need to buffer until we have a complete JSON object.
                        # The stream often sends a comma after a complete object.
                        # We can attempt to parse the content as a single object,
                        # but this is not foolproof. A more reliable way is to
                        # read until we find a complete JSON object.
                        # For simplicity, we'll strip any leading/trailing array brackets and process.

                        # More robust parsing for Gemini's varied streaming format
                        clean_buffer = buffer.strip(',[] \n')
                        if not clean_buffer:
                            continue

                        # A simple way to check if the string ends with a potential complete object.
                        # A better approach for production would be a stateful JSON parser.
                        if clean_buffer.endswith('}') or clean_buffer.endswith(']'):
                            try:
                                json_data = json.loads(clean_buffer)
                                text_part = json_data['candidates'][0]['content']['parts'][0]['text']

                                # Format and yield the chunk
                                chunk_response = {
                                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": COMPLETION_MODEL,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {
                                                "content": text_part
                                            },
                                            "finish_reason": None
                                        }
                                    ]
                                }
                                print(  f"Formatted Proxy Response Chunk: {json.dumps(chunk_response, indent=2)}")  # Log formatted chunk
                                yield f"data: {json.dumps(chunk_response)}\n\n"
                                buffer = ""  # Clear the buffer after a successful parse
                            except (json.JSONDecodeError, KeyError) as e:
                                # If parsing fails, it's a partial chunk, keep buffering
                                # The outer try-except will catch if the entire stream fails
                                continue

                    except Exception as e:
                        # Generic exception handler for safety
                        print(f"Error processing chunk: {e}")
                        continue

            # Send the final chunk to signal completion
            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            print(f"Final Proxy Response Chunk: {json.dumps(final_chunk, indent=2)}")  # Log final chunk
            # Signal end of stream with [DONE]
            yield "data: [DONE]\n\n"

        # Return the streaming response
        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
            error_message = f"An error occurred: {str(e)}"
            print(f"An error occurred during chat completion: {error_message}")  # Log the error

            def error_generator(message, model_name="error-model"):
                chunk_size = 50  # Adjust chunk size as needed
                for i in range(0, len(message), chunk_size):
                    chunk = message[i:i + chunk_size]
                    chunk_response = {
                        "id": f"chatcmpl-error-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": chunk
                                },
                                "finish_reason": None
                            }
                        ]
                    }
                    yield f"data: {json.dumps(chunk_response)}\n\n"

                # Final chunk to signal completion
                final_chunk = {
                    "id": f"chatcmpl-error-{os.urandom(12).hex()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }
                    ]
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return Response(error_generator(error_message), mimetype='text/event-stream')


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


if __name__ == '__main__':
    print("Starting proxy server on http://localhost:8081...")
    app.run(host='0.0.0.0', port=8081)