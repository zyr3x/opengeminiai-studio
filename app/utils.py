"""
Utility functions for Gemini-Proxy.
"""
import os
import json
import requests
import base64
import re
import mimetypes
import fnmatch
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
                name: profile for name, profile in all_profiles.items()
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
                name: profile for name, profile in all_profiles.items()
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
            # Handle web URL
            log(f"Downloading image from URL: {url}")
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            mime_type = response.headers.get("Content-Type", "image/jpeg")
            base64_data = base64.b64encode(response.content).decode('utf-8')
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

    return None

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

def process_path_injections(content: str) -> list:
    """
    Parses a string for `type_path=...` commands and injects file content.
    Returns a list of OpenAI-style content parts.
    """
    if not isinstance(content, str):
        return [] if content is None else [content]

    path_pattern = re.compile(r'(image|pdf|audio|code)_path=([^\s]+)')
    matches = list(path_pattern.finditer(content))

    if not matches:
        return [{"type": "text", "text": content}]

    new_content_parts = []
    last_end = 0
    for i, match in enumerate(matches):
        start, end = match.span()
        # Add preceding text part
        if start > last_end:
            new_content_parts.append({"type": "text", "text": content[last_end:start]})

        # --- Parse ignore patterns ---
        ignore_patterns_from_prompt = []
        command_end = end  # The end of the whole command defaults to end of path match

        # Define search area for ignore patterns: from end of path to start of next path
        next_match_start = len(content) if (i + 1 >= len(matches)) else matches[i + 1].start()
        search_region = content[end:next_match_start]

        # Find all 'ignore_x=...' parameters immediately following the path.
        param_pattern = re.compile(r'\s+(ignore_type|ignore_file|ignore_dir)=([^\s]+)')
        last_param_end = 0
        remaining_search_region = search_region
        while True:
            param_match = param_pattern.match(remaining_search_region)
            if not param_match:
                break

            ignore_key = param_match.group(1)
            value = param_match.group(2)
            patterns = value.split('|')

            if ignore_key == 'ignore_type':
                # For ignore_type=py|js, create patterns like *.py, *.js
                ignore_patterns_from_prompt.extend([f"*.{p}" for p in patterns])
            else:
                # For ignore_file and ignore_dir, use patterns as-is
                ignore_patterns_from_prompt.extend(patterns)

            match_end_pos = param_match.end()
            last_param_end += match_end_pos
            remaining_search_region = remaining_search_region[match_end_pos:]

        # Update the end of the full command (path + all ignores)
        if last_param_end > 0:
            command_end = end + last_param_end

        file_type = match.group(1)
        file_path_str = match.group(2)
        expanded_path = os.path.expanduser(file_path_str)

        if os.path.exists(expanded_path):
            if file_type == 'code':
                # Handle code import from file or directory, optionally zipping large volumes
                MAX_TEXT_SIZE_KB = 512
                MAX_BINARY_SIZE_KB = 8192  # 8 MB limit for binary parts

                candidate_files = []
                total_raw_size = 0

                # 1. Collect all files and calculate total size
                if os.path.isfile(expanded_path):
                    try:
                        size = os.path.getsize(expanded_path)
                        if size <= MAX_BINARY_SIZE_KB * 1024:
                            candidate_files.append((expanded_path, os.path.basename(expanded_path)))
                            total_raw_size += size
                    except Exception as e:
                        log(f"Error checking file size {expanded_path}: {e}")

                elif os.path.isdir(expanded_path):
                    # Patterns for files and dirs to ignore. Supports fnmatch.
                    ignore_patterns = [
                        '.git', '__pycache__', 'node_modules', 'venv', '.venv',
                        'build', 'dist', 'target', 'out', 'coverage', '.nyc_output', '*.egg-info', 'bin', 'obj',
                        'pkg',
                        '.idea', '.vscode', '.cache', '.pytest_cache',
                        '.DS_Store', 'Thumbs.db',
                        '*.log', '*.swp', '*.pyc', '*~', '*.bak', '*.tmp',
                        '*.zip', '*.tar.gz', '*.rar', '*.7z',
                        '*.o', '*.so', '*.dll', '*.exe', '*.a', '*.lib', '*.dylib',
                        '*.class', '*.jar', '*.war',
                        '*.pdb', '*.nupkg', '*.deps.json', '*.runtimeconfig.json',
                        '*.db', '*.sqlite', '*.sqlite3', 'data.mdb', 'lock.mdb',
                        '*.png', '*.jpg', '*.jpeg', '*.gif', '*.svg',
                        '*.woff', '*.woff2', '*.ttf', '*.otf', '*.eot', '*.ico',
                        '*.mp3', '*.wav', '*.mp4', '*.mov',
                        '*.min.js', '*.min.css', '*.map',
                        'package-lock-v1.json', 'package-lock.json', 'yarn.lock', 'poetry.lock',
                        'Pipfile.lock',
                    ]
                    ignore_patterns.extend(ignore_patterns_from_prompt)

                    for root, dirs, files in os.walk(expanded_path, topdown=True):
                        rel_root = os.path.relpath(root, expanded_path)
                        if rel_root == '.':
                            rel_root = ''

                        dirs[:] = [
                            d for d in dirs if not (
                                d.startswith('.') or
                                any(fnmatch.fnmatch(os.path.join(rel_root, d).replace(os.sep, '/'), p) for p in
                                    ignore_patterns)
                            )
                        ]

                        for filename in files:
                            if filename.startswith('.'):
                                continue

                            rel_filepath = os.path.join(rel_root, filename).replace(os.sep, '/')
                            if any(fnmatch.fnmatch(rel_filepath, p) or fnmatch.fnmatch(filename, p) for p in
                                   ignore_patterns):
                                continue

                            file_path = os.path.join(root, filename)

                            try:
                                size = os.path.getsize(file_path)
                                if total_raw_size + size <= MAX_BINARY_SIZE_KB * 1024:
                                    candidate_files.append(
                                        (file_path, os.path.relpath(file_path, expanded_path)))
                                    total_raw_size += size
                                elif total_raw_size == 0:
                                    log(
                                        f"Code import skipped: File {file_path} exceeds maximum binary limit of {MAX_BINARY_SIZE_KB} KB.")
                                    candidate_files = []
                                    total_raw_size = 0
                                    break
                                else:
                                    log(
                                        f"Code import stopped: Adding {file_path} would exceed maximum binary limit of {MAX_BINARY_SIZE_KB} KB.")
                                    break  # Stop adding files

                            except Exception as e:
                                log(f"Error checking file size {file_path}: {e}")
                                continue  # Skip problematic file

                        if total_raw_size > MAX_BINARY_SIZE_KB * 1024:
                            break  # Stop os.walk loop

                if not candidate_files:
                    msg = f"[Could not import code from {file_path_str}: No files found, or exceeded {MAX_BINARY_SIZE_KB} KB limit.]"
                    log(msg)
                    if os.path.isfile(expanded_path) or os.path.isdir(expanded_path):
                        new_content_parts.append({"type": "text", "text": msg})
                    else:
                        new_content_parts.append({"type": "text", "text": content[start:command_end]})
                    last_end = command_end
                    continue

                if total_raw_size <= MAX_TEXT_SIZE_KB * 1024:
                    injected_code_parts = []
                    for fpath, relative_path in candidate_files:
                        try:
                            with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                                code_content = f.read()
                            _, extension = os.path.splitext(fpath)
                            lang = extension.lstrip('.') if extension else ''
                            injected_code = (f"\n--- Code File: {relative_path} ---\n"
                                             f"```{lang}\n{code_content}\n```\n")
                            injected_code_parts.append(injected_code)
                        except Exception as e:
                            log(f"Error reading code file {fpath} for text injection: {e}")

                    full_injection_text = "".join(injected_code_parts)
                    header = (f"The following context contains code files imported from the path "
                              f"'{file_path_str}' (Total size: {total_raw_size / 1024:.2f} KB, TEXT MODE):\n\n")
                    new_content_parts.append({
                        "type": "text",
                        "text": header + full_injection_text
                    })
                    log(f"Successfully injected {len(injected_code_parts)} code files in text mode.")
                else:
                    msg = (f"[Code import from '{file_path_str}' skipped: "
                           f"Total size ({total_raw_size / 1024:.2f} KB) exceeds the text injection "
                           f"limit of {MAX_TEXT_SIZE_KB} KB.]")
                    log(msg)
                    new_content_parts.append({"type": "text", "text": msg})
                last_end = command_end
                continue  # Skip multimodal logic below

            try:
                mime_type, _ = mimetypes.guess_type(expanded_path)
                if not mime_type:
                    mime_type = 'application/octet-stream'  # Fallback
                    if expanded_path.lower().endswith('.pdf'):
                        mime_type = 'application/pdf'

                with open(expanded_path, 'rb') as f:
                    file_bytes = f.read()
                encoded_data = base64.b64encode(file_bytes).decode('utf-8')

                if file_type == 'image':
                    data_uri = f"data:{mime_type};base64,{encoded_data}"
                    new_content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                elif file_type == 'pdf' or file_type == 'audio':
                    new_content_parts.append({
                        "type": "inline_data",
                        "source": {
                            "media_type": mime_type,
                            "data": encoded_data
                        }
                    })
                log(f"Embedded local file: {expanded_path} as {mime_type}")
            except Exception as e:
                log(f"Error processing local file {expanded_path}: {e}")
                new_content_parts.append(
                    {"type": "text", "text": content[start:command_end]})  # Keep original text on error
        else:
            log(f"Local file not found: {expanded_path}")
            new_content_parts.append(
                {"type": "text", "text": content[start:command_end]})  # Keep original text if not found

        last_end = command_end

    # Add any remaining text after the last match
    if last_end < len(content):
        new_content_parts.append({"type": "text", "text": content[last_end:]})

    return new_content_parts
