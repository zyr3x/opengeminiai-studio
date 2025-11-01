import hashlib
import json
import time
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import date

from app.utils.core.optimization_utils import MAX_TOOL_OUTPUT_TOKENS, should_cache_tool, estimate_tokens, \
    get_cache_key
from app.utils.core.optimization import (
    clean_cache as sync_clean_cache,
    get_cached_tool_output as sync_get_cached_tool_output,
    cache_tool_output as sync_cache_tool_output,
    record_token_usage as sync_record_token_usage
)


# --- Rate Limiter ---
class AsyncRateLimiter:
    """Async rate limiter to prevent API throttling."""

    def __init__(self, requests_per_second: float = 5.0):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0
        self.lock = asyncio.Lock()

    async def wait_if_needed(self):
        """Wait if necessary to maintain rate limit."""
        async with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)

            self.last_request_time = time.time()

# Global rate limiter instance
_rate_limiter = AsyncRateLimiter(requests_per_second=5.0)

async def get_rate_limiter() -> AsyncRateLimiter:
    """Returns the global rate limiter instance."""
    return _rate_limiter

async def clean_cache():
    """Async: Cleans up expired entries from the cache by running sync version in an executor."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sync_clean_cache)


async def get_cached_tool_output(function_name: str, tool_args: dict) -> Optional[str]:
    """Async: Gets result from cache if present and not expired by running sync version in an executor."""
    await clean_cache()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        sync_get_cached_tool_output,
        function_name,
        tool_args
    )

async def cache_tool_output(function_name: str, tool_args: dict, output: str):
    """Async: Saves tool result to cache by running sync version in an executor."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        sync_cache_tool_output,
        function_name,
        tool_args,
        output
    )

async def execute_tools_parallel_async(
    tool_calls: List[Dict[str, Any]],
    executor_func
) -> List[Tuple[Dict[str, Any], Any]]:
    """
    Async: Executes multiple tool calls in parallel using asyncio.gather.

    Args:
        tool_calls: List of dicts with 'name' and 'args' keys
        executor_func: Async function that executes a single tool call

    Returns:
        List of tuples (tool_call_data, output)
    """
    tasks = []
    for tool_call in tool_calls:
        task = executor_func(tool_call['name'], tool_call['args'])
        tasks.append((tool_call, task))

    # Execute all tasks concurrently
    results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

    # Pair results with their corresponding tool calls
    output = []
    for (tool_call, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            error_output = json.dumps({"error": str(result)})
            output.append((tool_call, error_output))
        else:
            output.append((tool_call, result))

    return output

# --- Prompt Caching ---
_prompt_cache: Dict[str, Tuple[str, float]] = {}
_prompt_cache_lock = asyncio.Lock()
PROMPT_CACHE_TTL = 3600  # 1 hour

async def get_cached_context_id_async(
    api_key: str,
    upstream_url: str,
    model: str,
    system_text: str
) -> Optional[str]:
    """
    Async: Attempts to retrieve or create a cached context for the system prompt.
    Uses Gemini's prompt caching feature to reduce costs.
    """
    cache_key = hashlib.sha256(f"{model}:{system_text}".encode()).hexdigest()

    # Check local cache first
    async with _prompt_cache_lock:
        if cache_key in _prompt_cache:
            cached_id, timestamp = _prompt_cache[cache_key]
            if time.time() - timestamp < PROMPT_CACHE_TTL:
                return cached_id

    # Create new cached context via Gemini API
    try:
        from app.utils.quart.utils import get_async_session
        from app.utils.core.tools import log

        cache_url = f"{upstream_url}/v1beta/cachedContents"
        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': api_key
        }

        payload = {
            "model": f"models/{model}",
            "contents": [],
            "systemInstruction": {
                "parts": [{"text": system_text}]
            },
            "ttl": "3600s"  # Cache for 1 hour
        }

        session = await get_async_session()
        async with session.post(cache_url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                cache_name = data.get('name')

                if cache_name:
                    async with _prompt_cache_lock:
                        _prompt_cache[cache_key] = (cache_name, time.time())
                    log(f"✓ Created new cached context: {cache_name}")
                    return cache_name
            else:
                error_text = await response.text()
                log(f"Failed to create cached context: {response.status} - {error_text}")

    except Exception as e:
        log(f"Error creating cached context: {e}")

    return None

# --- Token Usage Tracking (async-compatible) ---
async def record_token_usage_async(api_key: str, model_name: str, input_tokens: int, output_tokens: int):
    """
    Async: Records token usage to the database.
    Runs the database operation in a thread pool to avoid blocking.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        sync_record_token_usage,
        api_key,
        model_name,
        input_tokens,
        output_tokens
    )
