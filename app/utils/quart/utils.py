"""
Async utility functions for Gemini-Proxy.
Provides async versions of key utilities for improved performance.
"""
import os
import json
import aiohttp
import aiofiles
import base64
import re
import random
import asyncio
from typing import Optional

# --- Global Settings ---
VERBOSE_LOGGING = True
DEBUG_CLIENT_LOGGING = False

# --- Caches for model info ---
cached_models_response = None
model_info_cache = {}
TOKEN_ESTIMATE_SAFETY_MARGIN = 0.95

# --- Async HTTP Session (connection pooling) ---
_async_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()

async def get_async_session() -> aiohttp.ClientSession:
    """
    Gets or creates a shared aiohttp ClientSession with connection pooling.
    This session should be reused for all HTTP requests for better performance.
    """
    global _async_session
    
    if _async_session is None or _async_session.closed:
        async with _session_lock:
            if _async_session is None or _async_session.closed:
                # Configure connection pooling and timeouts
                timeout = aiohttp.ClientTimeout(total=300, connect=30)
                connector = aiohttp.TCPConnector(
                    limit=100,  # Max connections
                    limit_per_host=30,  # Max connections per host
                    ttl_dns_cache=300,  # DNS cache TTL
                    keepalive_timeout=60
                )
                _async_session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector
                )
    
    return _async_session

async def close_async_session():
    """Closes the shared aiohttp session."""
    global _async_session
    if _async_session and not _async_session.closed:
        await _async_session.close()
        _async_session = None

def log(message: str):
    """Prints a message to the console if verbose logging is enabled."""
    if VERBOSE_LOGGING:
        print(message)

def debug(message: str):
    """Prints a message to the console if debug logging is enabled."""
    if DEBUG_CLIENT_LOGGING:
        print(message)

async def process_image_url_async(image_url: dict) -> Optional[dict]:
    """
    Async version: Processes an OpenAI image_url object and converts it to Gemini inline_data part.
    Supports both web URLs and Base64 data URIs.
    """
    url = image_url.get("url")
    if not url:
        return None

    try:
        if url.startswith("data:"):
            # Handle Base64 data URI (no async needed)
            match = re.match(r"data:(image/.+);base64,(.+)", url)
            if not match:
                log(f"Warning: Could not parse data URI.")
                return None
            mime_type, base64_data = match.groups()
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
        else:
            # Handle web URL with size check (async download)
            log(f"Downloading image from URL: {url}")
            MAX_IMAGE_SIZE_MB = 15
            MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024

            session = await get_async_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status()
                
                # Check Content-Length header first if available
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                    log(f"Skipping image from URL {url}: size from header ({int(content_length) / (1024*1024):.2f} MB) exceeds limit of {MAX_IMAGE_SIZE_MB} MB.")
                    return None

                # Read content in chunks
                content = b''
                async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
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

async def get_model_input_limit_async(model_name: str, api_key: str, upstream_url: str) -> int:
    """
    Async version: Fetches the input token limit for a given model from the Gemini API and caches it.
    """
    if model_name in model_info_cache:
        return model_info_cache[model_name].get("inputTokenLimit", 8192)

    try:
        log(f"Cache miss for {model_name}. Fetching model details from API...")
        GEMINI_MODEL_INFO_URL = f"{upstream_url}/v1beta/models/{model_name}"
        params = {"key": api_key}
        
        session = await get_async_session()
        async with session.get(GEMINI_MODEL_INFO_URL, params=params) as response:
            response.raise_for_status()
            model_info = await response.json()
            model_info_cache[model_name] = model_info
            return model_info.get("inputTokenLimit", 8192)
    except Exception as e:
        log(f"Error fetching model details for {model_name}: {e}. Using default limit of 8192.")
        return 8192

async def make_request_with_retry_async(
    url: str,
    headers: dict,
    json_data: dict,
    stream: bool = False,
    timeout: int = 300
) -> aiohttp.ClientResponse:
    """
    Async version: Makes a POST request with retry logic for 429 and connection errors.
    Uses connection pooling for better performance.
    """
    retries = 5
    backoff_factor = 1.0  # seconds
    
    session = await get_async_session()
    
    for i in range(retries):
        try:
            response = await session.post(
                url,
                headers=headers,
                json=json_data,
                timeout=aiohttp.ClientTimeout(total=timeout)
            )
            
            if response.status < 400:
                return response
            
            # Handle error status codes
            status_code = response.status
            if (status_code == 429 or status_code in [502, 503, 504]) and i < retries - 1:
                wait_time = 0
                # Check for Retry-After header from the API
                if 'Retry-After' in response.headers:
                    try:
                        wait_time = int(response.headers.get('Retry-After'))
                    except (ValueError, TypeError):
                        pass # Could be a date, ignore for now and use backoff

                if wait_time > 0:
                    wait_time += random.uniform(0, 1) # Add jitter
                elif status_code == 429:
                    # Exponential backoff for rate limiting, starting higher
                    wait_time = (backoff_factor * 10) * (2 ** i) + random.uniform(0, 3.0)
                else: # Server errors (502, 503, 504)
                    wait_time = backoff_factor * (2 ** i) + random.uniform(0, 1.0)

                log(f"Received status {status_code}. Retrying in {wait_time:.2f}s... (Attempt {i + 1}/{retries})")
                await asyncio.sleep(wait_time)
                continue
            else:
                error_text = await response.text()
                log(f"HTTP Error {status_code}: {error_text}")
                response.raise_for_status()
                
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if i < retries - 1:
                wait_time = backoff_factor * (2 ** i) + random.uniform(0, 0.5)
                log(f"Connection/Timeout error. Retrying in {wait_time:.2f}s... (Attempt {i + 1}/{retries})")
                await asyncio.sleep(wait_time)
                continue
            else:
                log(f"Connection/Timeout Error after final retry: {e}")
                raise
    
    raise aiohttp.ClientError(f"All {retries} retries failed.")

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

async def truncate_contents_async(contents: list, limit: int, current_query: str = None) -> list:
    """
    Async version: Truncates the 'contents' list by removing older messages
    until the estimated token count is within the specified limit.
    Uses smart truncation with summarization when available.
    """
    estimated_tokens = estimate_token_count(contents)
    if estimated_tokens <= limit:
        return contents

    log(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")

    # Try selective context first if enabled
    from app.config import config as app_config
    if current_query and app_config.SELECTIVE_CONTEXT_ENABLED:
        try:
            from app.utils.core.tools import context_selector

            # Note: context_selector might need async version too
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

    # Try smart truncation with summarization
    try:
        from app.utils.quart import optimization
        truncated = await optimization.smart_truncate_contents_async(contents, limit, keep_recent=5)
        final_tokens = estimate_token_count(truncated)
        log(f"Smart truncation complete. Final estimated token count: {final_tokens}")
        return truncated
    except Exception as e:
        log(f"Smart truncation failed, falling back to simple truncation: {e}")

    # Fallback to simple truncation
    truncated_contents = contents.copy()
    while estimate_token_count(truncated_contents) > limit and len(truncated_contents) > 1:
        truncated_contents.pop(1)

    final_tokens = estimate_token_count(truncated_contents)
    log(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents

def pretty_json(data):
    """Returns a pretty-printed JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)

async def read_file_async(file_path: str, mode: str = 'r') -> str:
    """Async file reading."""
    async with aiofiles.open(file_path, mode) as f:
        return await f.read()

async def write_file_async(file_path: str, content: str, mode: str = 'w'):
    """Async file writing."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    async with aiofiles.open(file_path, mode) as f:
        await f.write(content)
