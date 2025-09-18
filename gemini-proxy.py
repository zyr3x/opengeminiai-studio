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
            successful_response = None
            error_message = "Internal Server Error"
            try:
                response = requests.post(
                    GEMINI_STREAMING_URL,
                    headers=headers,
                    json=request_data,
                    stream=True,
                    timeout=300
                )
                response.raise_for_status()
                successful_response = response
            except HTTPError as e:
                error_message = f"Outgoing Gemini HTTPError: {e}"
                print(error_message)
            except (ConnectionError, Timeout, RequestException) as e:
                error_message = f"Outgoing Gemini HTTPError: {e}"
                print(error_message)

            if successful_response is None:
                time.sleep(5)
                error_response = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text":  error_message
                                    }
                                ],
                                "role": "model"
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 30,
                        "candidatesTokenCount": 0,
                        "totalTokenCount": 30
                    },
                    "modelVersion": "gemini-2.0-flash",
                    "responseId": "error_response_id"
                }
                successful_response = json.dumps(error_response)

            buffer = ""
            print(f"Outgoing Gemini Response: {successful_response}")
            if isinstance(successful_response, str):
                # Handle the error case, e.g., log the error and return an error chunk
                print(f"Error occurred, handling string response: {successful_response}")
                for chunk in successful_response.splitlines():
                    if chunk:
                        #Process string as a chunk
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
                                    print(f"Formatted Proxy Response Chunk: {json.dumps(chunk_response, indent=2)}")
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                    buffer = ""
                                except (json.JSONDecodeError, KeyError) as e:
                                    continue
                        except Exception as e:
                            print(f"Error processing chunk: {e}")
                            continue

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
                print(f"Final Proxy Response Chunk: {json.dumps(final_chunk, indent=2)}")
                yield "data: [DONE]\n\n"
                return
            else:
                for chunk in successful_response.iter_lines(decode_unicode=True):
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
                                    print(f"Formatted Proxy Response Chunk: {json.dumps(chunk_response, indent=2)}")
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                    buffer = ""
                                except (json.JSONDecodeError, KeyError) as e:
                                    continue

                        except Exception as e:
                            print(f"Error processing chunk: {e}")
                            continue

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
                print(f"Final Proxy Response Chunk: {json.dumps(final_chunk, indent=2)}")
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


if __name__ == '__main__':
    print("Starting proxy server on http://localhost:8081...")
    app.run(host='0.0.0.0', port=8081)