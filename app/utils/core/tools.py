import os
import json
import requests
import base64
import re

from app.db import get_db_connection, UPLOAD_FOLDER
from app.utils.core import logging
from app.utils.core.logging import log
from app.utils.core.config_loader import load_json_file, load_text_file_lines


PROMPT_OVERRIDES_FILE = 'var/config/prompt.json'
prompt_overrides = {}

SYSTEM_PROMPTS_FILE = 'var/config/system_prompts.json'
system_prompts = {}

cached_models_response = None
model_info_cache = {}
TOKEN_ESTIMATE_SAFETY_MARGIN = 0.95


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
                    'selected_mcp_tools': profile.get('selected_mcp_tools', [])
                }
                for name, profile in all_profiles.items()
                if profile.get('enabled', True)
            }
            log(f"Prompt overrides loaded from {PROMPT_OVERRIDES_FILE}. "
                f"{len(prompt_overrides)} of {len(all_profiles)} profiles are enabled.")
        except (json.JSONDecodeError, IOError) as e:
            log(f"Error loading prompt overrides: {e}")
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
                    'selected_mcp_tools': profile.get('selected_mcp_tools', [])
                }
                for name, profile in all_profiles.items()
                if profile.get('enabled', True) and profile.get('prompt')
            }
            log(f"System prompts loaded from {SYSTEM_PROMPTS_FILE}. "
                f"{len(system_prompts)} of {len(all_profiles)} profiles are enabled.")
        except (json.JSONDecodeError, IOError) as e:
            log(f"Error loading system prompts: {e}")
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
            match = re.match(r"data:(image/.+);base64,(.+)", url)
            if not match:
                log(f"Warning: Could not parse data URI.")
                return None
            mime_type, base64_data = match.groups()
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
        else:
            log(f"Downloading image from URL: {url}")
            MAX_IMAGE_SIZE_MB = 15
            MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024

            response = requests.get(url, timeout=20, stream=True)
            response.raise_for_status()

            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                log(f"Skipping image from URL {url}: size from header ({int(content_length) / (1024*1024):.2f} MB) exceeds limit of {MAX_IMAGE_SIZE_MB} MB.")
                return None

            content = b''
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                content += chunk
                if len(content) > MAX_IMAGE_SIZE_BYTES:
                    log(f"Skipping image from URL {url}: size exceeded {MAX_IMAGE_SIZE_MB} MB during download.")
                    return None

            mime_type = response.headers.get("Content-Type", "image/jpeg")
            base64_data = base64.b64encode(content).decode('utf-8')
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
    except Exception as e:
        log(f"Error processing image URL {url}: {e}")
        return None

def get_model_input_limit(model_name: str, api_key: str, upstream_url: str) -> int:
    """
    Fetches the input token limit for a given model from the Gemini API and caches it.
    """
    if model_name in model_info_cache:
        return model_info_cache[model_name].get("inputTokenLimit", 8192)

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
        log(f"Error fetching model details for {model_name}: {e}. Using default limit of 8192.")
        return 8192

from app.utils.core.optimization_utils import estimate_tokens, estimate_token_count

def truncate_contents(contents: list, limit: int, current_query: str = None) -> list:
    """
    Truncates the 'contents' list by removing older messages (but keeping the first one)
    until the estimated token count is within the specified limit.

    NEW: Uses smart truncation with summarization when available.

    Args:
        contents: List of messages
        limit: Token limit
        current_query: Current user query (optional) - enables selective context
    """
    estimated_tokens = estimate_token_count(contents)
    if estimated_tokens <= limit:
        return contents

    log(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")

    from app import config as app_config
    if current_query and app_config.config.SELECTIVE_CONTEXT_ENABLED:
        try:
            from app.utils.core import context_selector

            selected = context_selector.smart_context_window(
                messages=contents,
                current_query=current_query,
                max_tokens=limit,
                enabled=True
            )

            final_tokens = estimate_token_count(selected)
            if final_tokens <= limit:
                log(f"✓ Selective Context applied. Final estimated token count: {final_tokens}")
                return selected
            else:
                log(f"⚠ Selective Context result still exceeds limit, falling back...")
        except Exception as e:
            log(f"Selective Context failed, falling back: {e}")

    truncated_contents = contents
    try:
        from app.utils.core import optimization_utils
        truncated_contents = optimization_utils.smart_truncate_contents(contents, limit, keep_recent=5)
        log(f"Smart truncation applied. Message count: {len(contents)} -> {len(truncated_contents)}")
    except Exception as e:
        log(f"Smart truncation failed, will use simple truncation: {e}")

    # Always run simple truncation if smart truncation wasn't enough or failed
    if estimate_token_count(truncated_contents) > limit:
        log("Content still over limit after smart truncation, applying simple truncation...")
        final_truncated = truncated_contents.copy()
        # Keep first message (system prompt) and remove from the start of history
        while estimate_token_count(final_truncated) > limit and len(final_truncated) > 1:
            final_truncated.pop(1)
        truncated_contents = final_truncated


    final_tokens = estimate_token_count(truncated_contents)
    log(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents

def pretty_json(data):
    """Returns a pretty-printed JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)

def make_request_with_retry(url: str, headers: dict, json_data: dict, stream: bool = False, timeout: int = 300) -> requests.Response:
    """
    Makes a POST request with retry logic for 429 and connection errors.
    OPTIMIZED: Uses connection pooling for better performance.
    """
    from app.utils.flask import optimization
    session = optimization.get_http_session()
    rate_limiter = optimization.get_rate_limiter()

    rate_limiter.wait_if_needed()

    try:
        response = session.post(
            url,
            headers=headers,
            json=json_data,
            stream=stream,
            timeout=timeout
        )
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        log(f"Request failed after retries: {e}")
        raise


def save_config_to_file(config_str: str, file_path: str, config_name: str):
    """Saves a configuration string to a file, validating JSON first."""
    if not config_str.strip():
        if os.path.exists(file_path):
            os.remove(file_path)
            log(f"{config_name} config cleared.")
        return

    try:
        json.loads(config_str.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {config_name}: {e}")

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        f.write(config_str.strip())
    log(f"{config_name} updated and saved to {file_path}.")


DEFAULT_IGNORE_PATTERNS_PATH = 'etc/code_ignore_patterns.txt'

def _load_default_ignore_patterns(path: str) -> list[str]:
    """Helper to load default ignore patterns from a file."""
    return load_text_file_lines(path, default=[])


DEFAULT_CODE_IGNORE_PATTERNS: list[str] = _load_default_ignore_patterns(DEFAULT_IGNORE_PATTERNS_PATH)

def load_code_ignore_patterns(project_root: str, filename: str = '.aiignore') -> list[str]:
        """
        Loads code ignore patterns from a file in the project root and combines them with defaults.
        """
        ignore_patterns = DEFAULT_CODE_IGNORE_PATTERNS[:]
        ignore_file_path = os.path.join(project_root, filename)

        if os.path.exists(ignore_file_path):
            try:
                with open(ignore_file_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            normalized_line = line.replace('\\', '/')
                            ignore_patterns.append(normalized_line)
                log(f"Loaded {len(ignore_patterns) - len(DEFAULT_CODE_IGNORE_PATTERNS)} custom patterns from {filename}.")
            except Exception as e:
                log(f"Error reading ignore file {ignore_file_path}: {e}")
        else:
            log(f"No custom ignore file '{filename}' found. Using default patterns.")

        unique_patterns = []
        seen = set()
        for p in ignore_patterns:
            if p not in seen:
                unique_patterns.append(p)
                seen.add(p)

        return unique_patterns

EXTENSION_MAP_PATH = 'etc/extension_map.json'

def _load_extension_map(path: str) -> dict[str, str]:
    """Helper to load the language extension map from a JSON file."""
    return load_json_file(path, default={})


EXTENSION_TO_LANGUAGE_MAP: dict[str, str] = _load_extension_map(EXTENSION_MAP_PATH)


def get_code_language_from_filename(filename: str) -> str:
    """
    Determines the markdown code block language based on the file extension.
    """
    if not filename:
        return 'text'

    _, ext = os.path.splitext(filename.lower())

    return EXTENSION_TO_LANGUAGE_MAP.get(ext, 'text')



def format_tool_output_for_display(tool_parts: list, use_html_tags: bool = True) -> str | None:
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
            resp_text = str(resp_data['content'])
        else:
            resp_text = pretty_json(resp_data)

        if not resp_text:
            continue

        lang_specifier = 'json'
        try:
            parsed_json = json.loads(resp_text)
            pretty_text = json.dumps(parsed_json, indent=3, default=str)
            pretty_text = pretty_text.replace('\\n', '\n')
        except (json.JSONDecodeError, TypeError):
            pretty_text = resp_text

            filename_hint = resp_data.get('path') or resp_data.get('file_path') or resp_data.get('filename')
            if filename_hint:
                lang_specifier = get_code_language_from_filename(filename_hint)

        if use_html_tags:
            formatted_output = (f'\n<details><summary>Tool Output: `{name}`</summary>\n\n'
                                f'```{lang_specifier}\n{pretty_text}\n```\n\n</details>\n')
        else:
            formatted_output = (f'\nTool Output: `{name}`\n'
                                f'```{lang_specifier}\n{pretty_text}\n```\n')
        formatted_tool_outputs.append(formatted_output)

    if formatted_tool_outputs:
        return "".join(formatted_tool_outputs)

    return "" # Return empty string instead of None for consistency

def add_message_to_db(chat_id: int, role: str, parts: list):
    """Adds a message with its parts to the database and returns the new message ID."""
    conn = get_db_connection()
    cursor = conn.execute('INSERT INTO messages (chat_id, role, parts) VALUES (?, ?, ?)',
                 (chat_id, role, json.dumps(parts)))
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return message_id

def format_message_parts_for_ui(db_parts_json: str, use_html_tags: bool = True) -> dict:
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
                formatted_output = format_tool_output_for_display([part], use_html_tags=use_html_tags)
                if formatted_output:
                    text_parts.append(formatted_output)
        message_data['content'] = " ".join(text_parts).strip()
    except (json.JSONDecodeError, TypeError) as e:
        logging.log(f"Error parsing message parts for UI: {e}. Raw parts: {db_parts_json}")
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
                    logging.log(f"File not found when preparing for Gemini API: {file_path}")
                    reconstructed_parts.append({"text": f"[File not found: {os.path.basename(file_path)}]"})
            else:
                reconstructed_parts.append(part)
    except (json.JSONDecodeError, TypeError) as e:
        logging.log(f"Error preparing message parts for Gemini API: {e}. Raw parts: {db_parts_json}")
        reconstructed_parts.append({"text": f"Error preparing message: {e}"})
    return reconstructed_parts
