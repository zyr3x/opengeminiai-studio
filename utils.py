"""
Utility functions for Gemini-Proxy.
"""
import os
import json
import requests
import base64
import re

# --- Global Settings ---
VERBOSE_LOGGING = True

# --- Prompt Engineering Config ---
PROMPT_OVERRIDES_FILE = 'prompt_config.json'
prompt_overrides = {}

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
    """Loads prompt overrides from JSON file into the global prompt_overrides dict."""
    global prompt_overrides
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, 'r') as f:
                prompt_overrides = json.load(f)
            log(f"Prompt overrides loaded from {PROMPT_OVERRIDES_FILE}.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading prompt overrides: {e}")
            prompt_overrides = {}
    else:
        prompt_overrides = {}


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


# --- Helper Functions for Token Management ---

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
    return json.dumps(data, ensure_ascii=False)
