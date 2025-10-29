"""
Async optimization module to reduce token usage and improve performance.
Provides async versions of optimization functions for better concurrency.
"""
import hashlib
import json
import time
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import date

# --- Tool Result Cache (thread-safe) ---
_tool_output_cache = {}
from app.utils.core.optimization_utils import MAX_TOOL_OUTPUT_TOKENS, should_cache_tool, estimate_tokens, \
    can_execute_parallel

_cache_lock = asyncio.Lock()
CACHE_TTL = 300  # 5 minutes
CACHE_MAX_SIZE = 100

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
    """Async: Cleans up expired entries from the cache."""
    global _tool_output_cache
    
    async with _cache_lock:
        now = time.time()
        expired_keys = [
            key for key, (_, timestamp) in _tool_output_cache.items()
            if now - timestamp > CACHE_TTL
        ]
        for key in expired_keys:
            del _tool_output_cache[key]

        # If cache is too large, remove oldest entries
        if len(_tool_output_cache) > CACHE_MAX_SIZE:
            sorted_items = sorted(
                _tool_output_cache.items(),
                key=lambda x: x[1][1]
            )
            _tool_output_cache = dict(sorted_items[-CACHE_MAX_SIZE:])

def get_cache_key(function_name: str, tool_args: dict) -> str:
    """Generates a cache key for the tool."""
    args_str = json.dumps(tool_args, sort_keys=True, default=str)
    cache_string = f"{function_name}:{args_str}"
    return hashlib.md5(cache_string.encode()).hexdigest()

async def get_cached_tool_output(function_name: str, tool_args: dict) -> Optional[str]:
    """Async: Gets result from cache if present and not expired."""
    await clean_cache()
    
    cache_key = get_cache_key(function_name, tool_args)
    
    async with _cache_lock:
        if cache_key in _tool_output_cache:
            output, timestamp = _tool_output_cache[cache_key]
            if time.time() - timestamp < CACHE_TTL:
                return output
    
    return None

async def cache_tool_output(function_name: str, tool_args: dict, output: str):
    """Async: Saves tool result to cache."""
    cache_key = get_cache_key(function_name, tool_args)
    
    async with _cache_lock:
        _tool_output_cache[cache_key] = (output, time.time())

async def optimize_code_output_async(code: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Async: Optimizes code output to fit within token limit."""
    current_tokens = estimate_tokens(code)
    
    if current_tokens <= max_tokens:
        return code
    
    # Calculate how many lines we can keep
    lines = code.split('\n')
    target_lines = int(len(lines) * (max_tokens / current_tokens))
    
    if target_lines < 10:
        # If too small, return first and last few lines
        preview = '\n'.join(lines[:5] + ['...', f'[{len(lines) - 10} lines omitted]', '...'] + lines[-5:])
        return preview
    
    # Return first portion with indicator
    truncated = '\n'.join(lines[:target_lines])
    return f"{truncated}\n...\n[Output truncated: {len(lines) - target_lines} lines omitted]"

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

async def smart_truncate_contents_async(
    contents: list,
    limit: int,
    keep_recent: int = 5
) -> list:
    """
    Async: Smart truncation with summarization of old messages.
    Keeps the first message (system prompt), last N messages, and summarizes the middle.
    """
    from app.utils.core.tools import estimate_token_count, log
    
    if estimate_token_count(contents) <= limit:
        return contents
    
    if len(contents) <= keep_recent + 1:
        # Not enough messages to truncate intelligently
        return contents
    
    # Keep first message (usually system prompt)
    result = [contents[0]]
    
    # Messages to summarize (middle portion)
    middle_start = 1
    middle_end = len(contents) - keep_recent
    
    if middle_end <= middle_start:
        # Not enough middle messages, just keep recent
        return [contents[0]] + contents[-keep_recent:]
    
    middle_messages = contents[middle_start:middle_end]
    
    # Create a summary of the middle messages
    summary_parts = []
    for msg in middle_messages:
        role = msg.get('role', 'user')
        parts = msg.get('parts', [])
        
        for part in parts:
            if 'text' in part:
                text = part['text']
                # Take first 100 chars as preview
                preview = text[:100] + ('...' if len(text) > 100 else '')
                summary_parts.append(f"[{role}]: {preview}")
    
    # Add summary as a single message
    if summary_parts:
        summary_text = (
            f"[Context summary: {len(middle_messages)} messages omitted]\n" +
            '\n'.join(summary_parts[:5])  # Show preview of first 5
        )
        result.append({
            'role': 'user',
            'parts': [{'text': summary_text}]
        })
    
    # Add recent messages
    result.extend(contents[-keep_recent:])
    
    log(f"Smart truncation: kept 1 + {len(middle_messages)} summarized + {keep_recent} recent = {len(result)} messages")
    
    return result

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
    from app.utils.flask.optimization import _token_stats_lock
    def _record():
        try:
            import sqlite3
            from app.db import DATABASE_FILE

            with _token_stats_lock:
                conn = sqlite3.connect(DATABASE_FILE)
                key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
                today = date.today().isoformat()
            
            cursor = conn.execute('''
                SELECT input_tokens, output_tokens 
                FROM token_usage 
                WHERE date = ? AND key_hash = ? AND model_name = ?
            ''', (today, key_hash, model_name))
            
            row = cursor.fetchone()
            
            if row:
                new_input = row[0] + input_tokens
                new_output = row[1] + output_tokens
                conn.execute('''
                    UPDATE token_usage 
                    SET input_tokens = ?, output_tokens = ? 
                    WHERE date = ? AND key_hash = ? AND model_name = ?
                ''', (new_input, new_output, today, key_hash, model_name))
            else:
                conn.execute('''
                    INSERT INTO token_usage (date, key_hash, model_name, input_tokens, output_tokens)
                    VALUES (?, ?, ?, ?, ?)
                ''', (today, key_hash, model_name, input_tokens, output_tokens))
            
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Error recording token usage: {e}")
    
    # Run in thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _record)
