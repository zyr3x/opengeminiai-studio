"""
Utility functions for Gemini-Proxy.
"""
import os
import json
import requests
import base64
import re
import time
import random
from app.db import get_db_connection, UPLOAD_FOLDER # Import added for new utility functions

# --- Global Settings ---
VERBOSE_LOGGING = True

# --- Prompt Engineering Config ---
PROMPT_OVERRIDES_FILE = 'var/config/prompt.json'
prompt_overrides = {}

SYSTEM_PROMPTS_FILE = 'var/config/system_prompts.json'
system_prompts = {}

# --- Caches for model info ---
cached_models_response = None
model_info_cache = {}
TOKEN_ESTIMATE_SAFETY_MARGIN = 0.95  # Use 95% of the model's capacity

def set_verbose_logging(enabled: bool):
    """Sets the verbose logging status."""
    global VERBOSE_LOGGING
    VERBOSE_LOGGING = enabled
    print(f"Verbose logging has been {'enabled' if enabled else 'disabled'}.")

def log(message: str):
    """Prints a message to the console if verbose logging is enabled."""
    if VERBOSE_LOGGING:
        print(message)

def load_prompt_config():
    """
    Loads prompt overrides from JSON file into the global prompt_overrides dict.
    Only profiles marked as 'enabled' (or without the key) will be loaded.
    """
    global prompt_overrides
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, 'r') as f:
                all_profiles = json.load(f)

            prompt_overrides = {
                name: {
                    'enabled': profile.get('enabled', True),
                    'triggers': profile.get('triggers', []),
                    'overrides': profile.get('overrides', {}),
                    'disable_tools': profile.get('disable_tools', False),
                    'enable_native_tools': profile.get('enable_native_tools', False),
                    'selected_mcp_tools': profile.get('selected_mcp_tools', []) # New field
                }
                for name, profile in all_profiles.items()
                if profile.get('enabled', True)
            }
            log(f"Prompt overrides loaded from {PROMPT_OVERRIDES_FILE}. "
                f"{len(prompt_overrides)} of {len(all_profiles)} profiles are enabled.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading prompt overrides: {e}")
            prompt_overrides = {}
    else:
        prompt_overrides = {}

def load_system_prompt_config():
    """
    Loads preset system prompts from JSON file into the global system_prompts dict.
    Only profiles marked as 'enabled' (or without the key) and containing a prompt will be loaded.
    """
    global system_prompts
    if os.path.exists(SYSTEM_PROMPTS_FILE):
        try:
            with open(SYSTEM_PROMPTS_FILE, 'r') as f:
                all_profiles = json.load(f)

            system_prompts = {
                name: {
                    'enabled': profile.get('enabled', True),
                    'prompt': profile.get('prompt', ''),
                    'disable_tools': profile.get('disable_tools', False),
                    'enable_native_tools': profile.get('enable_native_tools', False),
                    'selected_mcp_tools': profile.get('selected_mcp_tools', []) # New field
                }
                for name, profile in all_profiles.items()
                if profile.get('enabled', True) and profile.get('prompt')
            }
            log(f"System prompts loaded from {SYSTEM_PROMPTS_FILE}. "
                f"{len(system_prompts)} of {len(all_profiles)} profiles are enabled.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading system prompts: {e}")
            system_prompts = {}
    else:
        system_prompts = {}

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
                log(f"Warning: Could not parse data URI.")
                return None
            mime_type, base64_data = match.groups()
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
        else:
            # Handle web URL with size check
            log(f"Downloading image from URL: {url}")
            MAX_IMAGE_SIZE_MB = 15
            MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024

            response = requests.get(url, timeout=20, stream=True)
            response.raise_for_status()

            # Check Content-Length header first if available
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                print(f"Skipping image from URL {url}: size from header ({int(content_length) / (1024*1024):.2f} MB) exceeds limit of {MAX_IMAGE_SIZE_MB} MB.")
                return None

            # Read content in chunks to prevent loading a huge file into memory
            content = b''
            for chunk in response.iter_content(chunk_size=1024 * 1024): # Read in 1MB chunks
                content += chunk
                if len(content) > MAX_IMAGE_SIZE_BYTES:
                    print(f"Skipping image from URL {url}: size exceeded {MAX_IMAGE_SIZE_MB} MB during download.")
                    return None

            mime_type = response.headers.get("Content-Type", "image/jpeg")
            base64_data = base64.b64encode(content).decode('utf-8')
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
    except Exception as e:
        print(f"Error processing image URL {url}: {e}")
        return None

def get_model_input_limit(model_name: str, api_key: str, upstream_url: str) -> int:
    """
    Fetches the input token limit for a given model from the Gemini API and caches it.
    """
    if model_name in model_info_cache:
        return model_info_cache[model_name].get("inputTokenLimit", 8192)  # Default to 8k if not found

    try:
        log(f"Cache miss for {model_name}. Fetching model details from API...")
        GEMINI_MODEL_INFO_URL = f"{upstream_url}/v1beta/models/{model_name}"
        params = {"key": api_key}
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

    log(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")

    # Keep the first message (often a system prompt) and the most recent ones.
    # We will remove messages from the second position (index 1).
    truncated_contents = contents.copy()
    while estimate_token_count(truncated_contents) > limit and len(truncated_contents) > 1:
        # Remove the oldest message after the initial system/user prompt
        truncated_contents.pop(1)

    final_tokens = estimate_token_count(truncated_contents)
    log(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents

def pretty_json(data):
    """Returns a pretty-printed JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)

def make_request_with_retry(url: str, headers: dict, json_data: dict, stream: bool = False, timeout: int = 300) -> requests.Response:
    """
    Makes a POST request with retry logic for 429 and connection errors.
    """
    retries = 5
    backoff_factor = 1.0  # seconds

    for i in range(retries):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=json_data,
                stream=stream,
                timeout=timeout
            )
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            # For 429, we retry with backoff. For other HTTP errors, we fail immediately.
            if e.response.status_code == 429 and i < retries - 1:
                wait_time = backoff_factor * (2 ** i) + random.uniform(0, 0.5)
                log(f"Rate limit (429) exceeded. Retrying in {wait_time:.2f}s... (Attempt {i + 1}/{retries})")
                time.sleep(wait_time)
                continue
            else:
                log(f"HTTP Error: {e}")
                raise  # Re-raise the exception to be handled by the caller
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if i < retries - 1:
                wait_time = backoff_factor * (2 ** i) + random.uniform(0, 0.5)
                log(f"Connection/Timeout error. Retrying in {wait_time:.2f}s... (Attempt {i + 1}/{retries})")
                time.sleep(wait_time)
                continue
            else:
                log(f"Connection/Timeout Error after final retry: {e}")
                raise  # Re-raise
        except requests.exceptions.RequestException as e:
            log(f"An unexpected request exception occurred: {e}")
            raise  # Re-raise

    # This part should not be reached if logic is correct, but as a fallback
    raise requests.exceptions.RequestException(f"All {retries} retries failed.")



def save_config_to_file(config_str: str, file_path: str, config_name: str):
    """Saves a configuration string to a file, validating JSON first."""
    if not config_str.strip():
        # Handle case where user clears config in editor
        if os.path.exists(file_path):
            os.remove(file_path)
            log(f"{config_name} config cleared.")
        return

    # 1. Validate JSON
    try:
        json.loads(config_str.strip())
    except json.JSONDecodeError as e:
        # Raise as ValueError so Flask controllers can catch it and redirect
        raise ValueError(f"Invalid JSON in {config_name}: {e}")

    # 2. Save file
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        f.write(config_str.strip())
    log(f"{config_name} updated and saved to {file_path}.")


def format_tool_output_for_display(tool_parts: list) -> str | None:
    """
    Formats the output from tool calls for display, especially when the model is silent.
    Handles different response payload structures and pretty-prints JSON.
    """
    formatted_tool_outputs = []
    for tool_part in tool_parts:
        func_resp = tool_part.get('functionResponse', {})
        name = func_resp.get('name', 'unknown_tool')
        resp_data = func_resp.get('response', {})

        resp_text = ""
        if 'text' in resp_data:
            resp_text = resp_data['text']
        elif 'content' in resp_data:
            # Use content field if text is missing (e.g., if output was mapped to 'content')
            resp_text = str(resp_data['content'])  # Ensure it's a string
        else:
            # If neither text nor content, dump the entire response payload dictionary
            resp_text = pretty_json(resp_data)

        if not resp_text:
            continue

        try:
            # Try to parse and pretty-print if it's a JSON string
            parsed_json = json.loads(resp_text)
            pretty_text = json.dumps(parsed_json, indent=3, default=str)
            pretty_text = pretty_text.replace('\\n', '\n')
        except (json.JSONDecodeError, TypeError):
            # If it fails, use the response text as is
            pretty_text = resp_text

        formatted_output = (f'\n<details><summary>Tool Output: `{name}`</summary>\n\n'
                            f'```json\n{pretty_text}\n```\n\n</details>\n')
        formatted_tool_outputs.append(formatted_output)

    if formatted_tool_outputs:
        return "".join(formatted_tool_outputs)

    return "" # Return empty string instead of None for consistency

def add_message_to_db(chat_id: int, role: str, parts: list):
    """Adds a message with its parts to the database."""
    conn = get_db_connection()
    conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)',
                 (chat_id, role, json.dumps(parts)))
    conn.commit()
    conn.close()

def format_message_parts_for_ui(db_parts_json: str) -> dict:
    """
    Formats a message's parts (from DB JSON string) for display in the UI.
    Converts file_data paths to /uploads URLs.
    """
    message_data = {'content': '', 'files': []}
    try:
        parts = json.loads(db_parts_json)
        text_parts = []
        for part in parts:
            if 'text' in part:
                text_parts.append(part['text'])
            elif 'file_data' in part:
                file_path = part['file_data']['path']
                if os.path.exists(file_path):
                    # Create a relative path for the URL
                    relative_path = os.path.relpath(file_path, UPLOAD_FOLDER)
                    file_url = f"/uploads/{relative_path.replace(os.sep, '/')}"
                    message_data['files'].append({
                        'url': file_url,
                        'mimetype': part['file_data']['mime_type'],
                        'name': os.path.basename(file_path)
                    })
                else:
                    text_parts.append(f"[File not found: {os.path.basename(file_path)}]")
            elif 'functionResponse' in part:
                # Format tool output for UI display
                formatted_output = format_tool_output_for_display([part])
                if formatted_output:
                    text_parts.append(formatted_output)
        message_data['content'] = " ".join(text_parts).strip()
    except (json.JSONDecodeError, TypeError) as e:
        log(f"Error parsing message parts for UI: {e}. Raw parts: {db_parts_json}")
        message_data['content'] = f"Error displaying message: {e}"
    return message_data

def prepare_message_parts_for_gemini(db_parts_json: str) -> list:
    """
    Prepares a message's parts (from DB JSON string) for sending to the Gemini API.
    Reads file_data paths and converts them to Base64 inline_data.
    """
    reconstructed_parts = []
    try:
        parts = json.loads(db_parts_json)
        for part in parts:
            if 'file_data' in part:
                file_path = part['file_data']['path']
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                    file_base64 = base64.b64encode(file_content).decode('utf-8')
                    reconstructed_parts.append({
                        "inline_data": {"mime_type": part['file_data']['mime_type'], "data": file_base64}
                    })
                else:
                    log(f"File not found when preparing for Gemini API: {file_path}")
                    reconstructed_parts.append({"text": f"[File not found: {os.path.basename(file_path)}]"})
            else:
                reconstructed_parts.append(part)
    except (json.JSONDecodeError, TypeError) as e:
        log(f"Error preparing message parts for Gemini API: {e}. Raw parts: {db_parts_json}")
        reconstructed_parts.append({"text": f"Error preparing message: {e}"})
    return reconstructed_parts
