import os
import json
import aiohttp
import aiofiles
import base64
import re
import random
import asyncio
from typing import Optional

from app.utils.core.logging import log
from app.utils.core.tools import model_info_cache
from app.utils.core.optimization_utils import estimate_token_count

_async_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()
async def get_async_session() -> aiohttp.ClientSession:
    global _async_session
    if _async_session is None or _async_session.closed:
        async with _session_lock:
            if _async_session is None or _async_session.closed:
                timeout = aiohttp.ClientTimeout(total=300, connect=30)
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=30,
                    ttl_dns_cache=300,
                    keepalive_timeout=60
                )
                _async_session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector
                )
    return _async_session
async def close_async_session():
    global _async_session
    if _async_session and not _async_session.closed:
        await _async_session.close()
        _async_session = None
async def process_image_url_async(image_url: dict) -> Optional[dict]:
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

            session = await get_async_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status()

                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                    log(f"Skipping image from URL {url}: size from header ({int(content_length) / (1024*1024):.2f} MB) exceeds limit of {MAX_IMAGE_SIZE_MB} MB.")
                    return None

                content = b''
                async for chunk in response.content.iter_chunked(1024 * 1024):
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
    retries = 2
    backoff_factor = 1.0
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

            status_code = response.status
            if (status_code == 429 or status_code in [502, 503, 504]) and i < retries - 1:
                wait_time = 0
                if 'Retry-After' in response.headers:
                    try:
                        wait_time = int(response.headers.get('Retry-After'))
                    except (ValueError, TypeError):
                        pass

                if wait_time > 0:
                    wait_time += random.uniform(0, 1)
                elif status_code == 429:
                    wait_time = (backoff_factor * 10) * (2 ** i) + random.uniform(0, 3.0)
                else:
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
async def truncate_contents_async(contents: list, limit: int, current_query: str = None) -> list:
    estimated_tokens = estimate_token_count(contents)
    if estimated_tokens <= limit:
        return contents
    log(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")
    from app.config import config as app_config
    if current_query and app_config.SELECTIVE_CONTEXT_ENABLED:
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
    from app.utils.core import optimization_utils
    truncated_contents = optimization_utils.smart_truncate_contents(contents, limit, keep_recent=5)
    if estimate_token_count(truncated_contents) > limit:
        log("Content still over limit after smart truncation, applying simple truncation...")
        final_truncated = truncated_contents.copy()
        while estimate_token_count(final_truncated) > limit and len(final_truncated) > 1:
            final_truncated.pop(1)
        truncated_contents = final_truncated
    final_tokens = estimate_token_count(truncated_contents)
    log(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents
async def read_file_async(file_path: str, mode: str = 'r') -> str:
    async with aiofiles.open(file_path, mode) as f:
        return await f.read()
async def write_file_async(file_path: str, content: str, mode: str = 'w'):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    async with aiofiles.open(file_path, mode) as f:
        await f.write(content)


async def summarize_with_aux_model_async(content: str, tool_name: str) -> str:
    if not config.AGENT_AUX_MODEL_ENABLED:
        return content

    log(f"Summarizing output of tool '{tool_name}' with model '{config.AGENT_AUX_MODEL_NAME}' (async)")
    prompt_template = (
        "You are an expert at summarizing content for other AI models. "
        "The output from the tool `{tool_name}` is too long to be processed. "
        "Your task is to summarize it, keeping all crucial information like file paths, "
        "function names, class names, error messages, and key results. "
        "The summary MUST be concise but comprehensive. "
        "Original content:\n\n---\n\n{content}"
    )
    prompt = prompt_template.format(tool_name=tool_name, content=content)

    try:
        GEMINI_URL = f"{config.UPSTREAM_URL}/v1beta/models/{config.AGENT_AUX_MODEL_NAME}:generateContent"
        headers = {'Content-Type': 'application/json', 'X-goog-api-key': config.API_KEY}
        request_data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
        }

        response = await make_request_with_retry_async(
            url=GEMINI_URL,
            headers=headers,
            json_data=request_data,
            stream=False,
            timeout=120
        )
        response_data = await response.json()
        summary = response_data['candidates'][0]['content']['parts'][0]['text']
        original_tokens = estimate_token_count([{"parts": [{"text": content}]}])
        summary_tokens = estimate_token_count([{"parts": [{"text": summary}]}])
        log(f"Summarization complete. Tokens reduced from {original_tokens} to {summary_tokens}")
        return summary
    except Exception as e:
        log(f"Error during summarization with auxiliary model: {e}")
        from app.utils.core.optimization_utils import optimize_tool_output
        return optimize_tool_output(content, tool_name)
