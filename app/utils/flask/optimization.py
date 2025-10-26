"""
Optimization module to reduce token usage and improve performance.
PHASE 1: Caching, output optimization, smart truncation
PHASE 2: Connection pooling, rate limiting, prompt caching, parallel execution
"""
import hashlib
import json
import time
import re
import threading
from typing import Optional, Tuple, List, Dict
from datetime import date
from app.db import get_db_connection
from functools import wraps
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Tool Result Cache ---
_tool_output_cache = {}
_cache_lock = threading.Lock() # Added lock for thread safety
CACHE_TTL = 300  # 5 minutes
CACHE_MAX_SIZE = 100  # Maximum entries in the cache

# --- Optimization Constants ---
MAX_TOOL_OUTPUT_TOKENS = 1000  # Maximum size of tool output
MAX_FILE_PREVIEW_LINES = 50    # Maximum lines for file preview
MAX_DIFF_LINES = 100           # Maximum lines for diff

def clean_cache():
    """Cleans up expired entries from the cache"""
    global _tool_output_cache
    with _cache_lock:
        now = time.time()
        expired_keys = [
            key for key, (_, timestamp) in _tool_output_cache.items()
        if now - timestamp > CACHE_TTL
    ]
        for key in expired_keys:
            if key in _tool_output_cache:
                del _tool_output_cache[key]

        # If the cache is too large, remove the oldest entries
        if len(_tool_output_cache) > CACHE_MAX_SIZE:
            sorted_items = sorted(
                _tool_output_cache.items(),
                key=lambda x: x[1][1]  # Sort by timestamp
            )
            # Keep only the CACHE_MAX_SIZE newest entries
            _tool_output_cache = dict(sorted_items[-CACHE_MAX_SIZE:])

def get_cache_key(function_name: str, tool_args: dict) -> str:
    """Generates a cache key for the tool"""
    # Sort keys for hash stability
    args_str = json.dumps(tool_args, sort_keys=True, default=str)
    cache_string = f"{function_name}:{args_str}"
    return hashlib.md5(cache_string.encode()).hexdigest()

def get_cached_tool_output(function_name: str, tool_args: dict) -> Optional[str]:
    """Gets result from cache if present and not expired"""
    clean_cache()  # Periodically clean cache

    cache_key = get_cache_key(function_name, tool_args)
    with _cache_lock:
        if cache_key in _tool_output_cache:
            output, timestamp = _tool_output_cache[cache_key]
            if time.time() - timestamp < CACHE_TTL:
                return output

    return None

def cache_tool_output(function_name: str, tool_args: dict, output: str):
    """Saves tool result to cache"""
    with _cache_lock:
        cache_key = get_cache_key(function_name, tool_args)
        _tool_output_cache[cache_key] = (output, time.time())

def should_cache_tool(function_name: str) -> bool:
    """Determines whether to cache the results of this tool"""
    # Do not cache modifying operations
    non_cacheable = ['apply_patch', 'git_status']

    # Cache read operations
    cacheable = [
        'list_files', 'get_file_content', 'list_symbols_in_file',
        'get_code_snippet', 'search_codebase', 'git_log', 'git_diff',
        'git_show', 'git_blame', 'list_recent_changes',
        'analyze_file_structure', 'get_file_stats'
    ]

    return function_name in cacheable

# --- Tool Output Optimization ---

def estimate_tokens(text: str) -> int:
    """Improved token estimation"""
    # More accurate formula considering spaces and special characters
    # Approximately 3.5 characters per token for mixed text
    return int(len(text) / 3.5)

def optimize_code_output(code: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Optimizes code output"""
    tokens = estimate_tokens(code)

    if tokens <= max_tokens:
        return code

    lines = code.split('\n')
    total_lines = len(lines)

    # Show file beginning and end
    keep_lines = int((max_tokens * 3.5) / (len(code) / total_lines))
    head_lines = keep_lines // 2
    tail_lines = keep_lines // 2

    if total_lines <= keep_lines:
        return code

    result = '\n'.join(lines[:head_lines])
    result += f"\n\n... [{total_lines - keep_lines} lines truncated] ...\n\n"
    result += '\n'.join(lines[-tail_lines:])

    return result

def optimize_diff_output(diff: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Optimizes git diff output"""
    tokens = estimate_tokens(diff)

    if tokens <= max_tokens:
        return diff

    lines = diff.split('\n')

    # For diff, the priority is changed lines (+ and -)
    important_lines = []
    context_lines = []

    for i, line in enumerate(lines):
        if line.startswith(('+', '-', '@@', 'diff', 'index')):
            important_lines.append((i, line))
        elif line.strip():  # Context lines
            context_lines.append((i, line))

    # Take all important lines and a bit of context
    max_lines = int((max_tokens * 3.5) / (len(diff) / len(lines)))

    if len(important_lines) <= max_lines:
        return diff

    # Ограничиваем важные строки
    result_lines = important_lines[:max_lines]
    total_lines = len(lines)
    shown_lines = len(result_lines)

    result = '\n'.join(line for _, line in result_lines)
    result += f"\n\n... [Showing {shown_lines} of {total_lines} lines] ...\n"

    return result

def optimize_list_output(text: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Optimizes file list output"""
    tokens = estimate_tokens(text)

    if tokens <= max_tokens:
        return text

    lines = text.split('\n')
    total_lines = len(lines)

    # For lists - show the beginning
    max_lines = int((max_tokens * 3.5) / (len(text) / total_lines))

    if total_lines <= max_lines:
        return text

    result = '\n'.join(lines[:max_lines])
    result += f"\n... [Showing {max_lines} of {total_lines} items] ..."

    return result

def optimize_tool_output(output: str, function_name: str) -> str:
    """
    Intelligently optimizes tool output to reduce token usage.
    """
    if not output or not isinstance(output, str):
        return output

    tokens = estimate_tokens(output)

    # If the output is small, do not modify
    if tokens <= MAX_TOOL_OUTPUT_TOKENS:
        return output

    # Determine the output type and apply the appropriate strategy
    if '```diff' in output or 'git diff' in output.lower():
        return optimize_diff_output(output)

    elif '```' in output:  # Code block
        # Extract code between ```
        code_match = re.search(r'```[\w]*\n(.*?)\n```', output, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            optimized_code = optimize_code_output(code)
            return output.replace(code, optimized_code)
        return optimize_code_output(output)

    elif function_name in ['list_files', 'list_recent_changes', 'list_symbols_in_file']:
        return optimize_list_output(output)

    else:
        # General truncation for other types
        max_chars = MAX_TOOL_OUTPUT_TOKENS * 4
        if len(output) > max_chars:
            return output[:max_chars] + f"\n\n... [Output truncated from {len(output)} to {max_chars} chars]"

    return output

# --- Smart History Truncation ---

def summarize_message(message: dict) -> str:
    """Creates a brief summary of the message"""
    role = message.get('role', 'unknown')
    parts = message.get('parts', [])

    # Extract text
    text_parts = []
    for part in parts:
        if 'text' in part:
            text_parts.append(part['text'])

    full_text = ' '.join(text_parts)

    # Limit summary length
    max_summary_length = 100
    if len(full_text) > max_summary_length:
        # Take the first words
        words = full_text.split()
        summary = ' '.join(words[:15]) + '...'
    else:
        summary = full_text

    return f"[{role}]: {summary}"

def smart_truncate_contents(contents: list, limit: int, keep_recent: int = 5) -> list:
    """
    Intelligently compresses message history instead of deleting it.
    Keeps the system prompt, the last N messages, and creates a brief summary of the rest.
    """
    from app.utils.core.tools import estimate_token_count

    tokens = estimate_token_count(contents)

    if tokens <= limit:
        return contents

    if len(contents) <= keep_recent + 1:
        # Too few messages, just truncate
        return contents[:1] + contents[-(keep_recent-1):]

    # Always keep the system prompt (first message)
    result = [contents[0]]

    # The last keep_recent messages are also kept
    recent_messages = contents[-keep_recent:]

    # Middle messages are compressed into a brief summary
    middle_messages = contents[1:-keep_recent]

    if middle_messages:
        summaries = [summarize_message(msg) for msg in middle_messages]
        summary_text = "Previous conversation summary:\n" + "\n".join(summaries)

        result.append({
            "role": "user",
            "parts": [{"text": summary_text}]
        })

    # Add recent messages
    result.extend(recent_messages)

    # Check if we fit within the limit
    new_tokens = estimate_token_count(result)

    if new_tokens > limit:
        # If still not fitting, decrease keep_recent
        if keep_recent > 2:
            return smart_truncate_contents(contents, limit, keep_recent - 1)
        else:
            # Last resort - simple truncation
            return result[:1] + result[-2:]

    return result

# --- Stats and Metrics ---

# Lock for thread-safe DB operations on token stats
_token_stats_lock = threading.Lock()


def record_token_usage(api_key: str, model_name: str, input_tokens: int, output_tokens: int):
    """Records token usage for a specific API key and model, persisting to DB."""
    if not api_key or not model_name:
        return

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    today = date.today().strftime('%Y-%m-%d')
    conn = None

    with _token_stats_lock:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 1. Attempt UPDATE (if row exists)
            cursor.execute("""
                UPDATE token_usage
                SET input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?
                WHERE date = ? AND key_hash = ? AND model_name = ?
            """, (input_tokens, output_tokens, today, key_hash, model_name))

            # 2. If no row was updated, INSERT (first usage of the day)
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO token_usage (date, key_hash, model_name, input_tokens, output_tokens)
                    VALUES (?, ?, ?, ?, ?)
                """, (today, key_hash, model_name, input_tokens, output_tokens))

            conn.commit()
        except Exception as e:
            # In a real app, use a logger here
            print(f"Error recording token usage to DB: {e}")
        finally:
            if conn:
                conn.close()


def get_key_token_stats() -> List[Dict]:
    """Returns token usage statistics structured by API key, aggregated from DB."""
    stats = {}
    conn = None
    with _token_stats_lock:
        try:
            conn = get_db_connection()
            # Aggregate total usage across all models and days for each key
            results = conn.execute("""
                SELECT
                    key_hash,
                    model_name,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens
                FROM token_usage
                GROUP BY key_hash, model_name
            """).fetchall()

            for row in results:
                key_hash = row['key_hash']
                model_name = row['model_name']
                input_t = row['input_tokens']
                output_t = row['output_tokens']

                if key_hash not in stats:
                    stats[key_hash] = {
                        'key_id': key_hash,
                        'models': {},
                        'total_input': 0,
                        'total_output': 0,
                        'total_tokens': 0,
                    }

                key_stats = stats[key_hash]
                key_stats['models'][model_name] = {'input': input_t, 'output': output_t}
                key_stats['total_input'] += input_t
                key_stats['total_output'] += output_t
                key_stats['total_tokens'] += input_t + output_t

        except Exception as e:
            # In a real app, use a logger here
            print(f"Error retrieving token usage from DB: {e}")
        finally:
            if conn:
                conn.close()

    return list(stats.values())

def reset_token_stats():
    """Resets the token usage statistics by clearing the database table."""
    conn = None
    with _token_stats_lock:
        try:
            conn = get_db_connection()
            conn.execute("DELETE FROM token_usage")
            conn.commit()
        except Exception as e:
            print(f"Error resetting token usage in DB: {e}")
        finally:
            if conn:
                conn.close()

_metrics_lock = threading.Lock() # Added lock for thread safety
_metrics = {
    'cache_hits': 0,
    'cache_misses': 0,
    'tokens_saved': 0,
    'requests_optimized': 0,
    'tool_calls_total': 0,  # New metric for total tool execution count
    'tool_calls_external': 0, # New metric for external (non-builtin) tool execution
}

def record_tool_call(is_builtin: bool = True):
    """Records a tool call"""
    with _metrics_lock:
        _metrics['tool_calls_total'] += 1
        if not is_builtin:
            _metrics['tool_calls_external'] += 1

def record_cache_hit():
    """Records a cache hit"""
    with _metrics_lock:
        _metrics['cache_hits'] += 1

def record_cache_miss():
    """Records a cache miss"""
    with _metrics_lock:
        _metrics['cache_misses'] += 1

def record_tokens_saved(count: int):
    """Records tokens saved"""
    with _metrics_lock:
        _metrics['tokens_saved'] += count

def record_optimization():
    """Records an optimized request"""
    with _metrics_lock:
        _metrics['requests_optimized'] += 1

def get_metrics() -> dict:
    """Returns optimization metrics"""
    with _metrics_lock:
        total_cache_requests = _metrics['cache_hits'] + _metrics['cache_misses']
        cache_hit_rate = (_metrics['cache_hits'] / total_cache_requests * 100) if total_cache_requests > 0 else 0

        metrics_copy = _metrics.copy()

    with _cache_lock:
        cache_size = len(_tool_output_cache)


    return {
        **metrics_copy,
        'cache_hit_rate': f"{cache_hit_rate:.1f}%",
        'cache_size': cache_size
    }

def reset_metrics():
    """Resets the metrics"""
    global _metrics
    with _metrics_lock:
        _metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'tokens_saved': 0,
            'requests_optimized': 0,
            'tool_calls_total': 0,
            'tool_calls_external': 0,
        }

    # Also reset key-based token stats
    reset_token_stats()

    # Placeholder for the actual tool cache implementation (e.g., LRUCache)
    # Using a simple dictionary for demonstration/metrics calculation.
    with _cache_lock:
        _tool_output_cache.clear()

# ============================================================================
# PHASE 2: ADVANCED OPTIMIZATION
# ============================================================================

# --- Connection Pooling ---

_http_session = None
_session_lock = threading.Lock()

def get_http_session() -> requests.Session:
    """
    Returns a configured HTTP session with connection pooling and a retry strategy.
    Reuses connections to improve performance.
    """
    global _http_session

    if _http_session is None:
        with _session_lock:
            # Double-check locking pattern
            if _http_session is None:
                session = requests.Session()

                # Configure retry strategy for rate limiting and server errors
                retry_strategy = Retry(
                    total=5,  # Increased retries
                    status_forcelist=[429, 502, 503, 504], # Focus on retryable errors
                    backoff_factor=10, # Significantly increased backoff (e.g., 10s, 20s, 40s...)
                    allowed_methods=["GET", "POST"], # Only retry methods used by the proxy
                    respect_retry_after_header=True # Honor Retry-After header from the API
                )

                # Adapter with connection pooling
                adapter = HTTPAdapter(
                    pool_connections=10,    # Number of connection pools
                    pool_maxsize=20,        # Maximum connections in the pool
                    max_retries=retry_strategy,
                    pool_block=False        # Do not block when limit is reached
                )

                session.mount("http://", adapter)
                session.mount("https://", adapter)

                _http_session = session

    return _http_session

def close_http_session():
    """Closes the HTTP session (called on shutdown)"""
    global _http_session
    if _http_session is not None:
        _http_session.close()
        _http_session = None

# --- Rate Limiting ---

class RateLimiter:
    """
    Thread-safe rate limiter for limiting request frequency.
    Uses sliding window algorithm.
    """
    def __init__(self, max_calls: int, period: int):
        """
        Args:
            max_calls: Maximum number of calls
            period: Period in seconds
        """
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = threading.Lock()

    def __call__(self, func):
        """Decorator to apply rate limiting"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.lock:
                now = time.time()

                # Remove old calls (outside the window)
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()

                # If limit is reached, wait
                if len(self.calls) >= self.max_calls:
                    sleep_time = self.period - (now - self.calls[0]) + 0.01
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        now = time.time()
                        # Clear old ones after sleep
                        while self.calls and now - self.calls[0] >= self.period:
                            self.calls.popleft()

                # Add current call
                self.calls.append(time.time())

            return func(*args, **kwargs)

        return wrapper

    def wait_if_needed(self):
        """Waits if rate limit is reached (without executing function)"""
        with self.lock:
            now = time.time()

            # Remove old calls
            while self.calls and now - self.calls[0] >= self.period:
                self.calls.popleft()

            # If limit is reached, wait
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0]) + 0.01
                if sleep_time > 0:
                    time.sleep(sleep_time)

# Global rate limiter for Gemini API
# Default: 60 requests per minute (can be configured via env)
_gemini_rate_limiter = None

def get_rate_limiter(max_calls: int = 60, period: int = 60) -> RateLimiter:
    """Returns the global rate limiter"""
    global _gemini_rate_limiter
    if _gemini_rate_limiter is None:
        _gemini_rate_limiter = RateLimiter(max_calls, period)
    return _gemini_rate_limiter

# --- Parallel Tool Execution ---

_tool_executor = None
_executor_lock = threading.Lock()

def get_tool_executor(max_workers: int = 5) -> ThreadPoolExecutor:
    """
    Returns a thread pool executor for parallel tool execution.
    """
    global _tool_executor

    if _tool_executor is None:
        with _executor_lock:
            if _tool_executor is None:
                _tool_executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="tool_executor"
                )

    return _tool_executor

def shutdown_tool_executor():
    """Shuts down the thread pool executor"""
    global _tool_executor
    if _tool_executor is not None:
        _tool_executor.shutdown(wait=True)
        _tool_executor = None

def execute_tools_parallel(tool_calls: List[Dict]) -> List[Tuple[Dict, str]]:
    """
    Executes multiple tool calls in parallel.

    Args:
        tool_calls: List of dictionaries with 'name' and 'args'

    Returns:
        List of tuples (tool_call, result)
    """
    if not tool_calls:
        return []

    # Import here to avoid circular dependencies
    from app.utils.quart import mcp_handler

    executor = get_tool_executor()
    futures = {}

    # Start all tool calls in parallel
    for tool_call in tool_calls:
        future = executor.submit(
            mcp_handler.execute_mcp_tool,
            tool_call.get('name'),
            tool_call.get('args', {})
        )
        futures[future] = tool_call

    # Collect results as they complete
    results = []
    for future in as_completed(futures):
        tool_call = futures[future]
        try:
            result = future.result(timeout=120)  # 2 minutes per tool
            results.append((tool_call, result))
        except Exception as e:
            error_msg = f"Error executing {tool_call.get('name')}: {e}"
            results.append((tool_call, error_msg))

    return results

def can_execute_parallel(tool_calls: List[Dict]) -> bool:
    """
    Determines if tool calls can be executed in parallel.
    Some tools must be executed sequentially (e.g., apply_patch).
    """
    # Tools that cannot be executed in parallel
    sequential_only = {'apply_patch'}

    # If there is at least one sequential tool, execute all sequentially
    for tool_call in tool_calls:
        if tool_call.get('name') in sequential_only:
            return False

    # Can execute in parallel if there is more than one tool
    return len(tool_calls) > 1

# --- Prompt Caching (Gemini Context Caching API) ---

_cached_contexts = {}
_context_cache_lock = threading.Lock()

class CachedContext:
    """Represents a cached context on the Gemini side"""
    def __init__(self, cache_id: str, created_at: float, ttl: int = 3600):
        self.cache_id = cache_id
        self.created_at = created_at
        self.ttl = ttl
        self.last_used = created_at

    def is_expired(self) -> bool:
        """Checks if the cache has expired"""
        return time.time() - self.created_at > self.ttl

    def touch(self):
        """Updates the last used time"""
        self.last_used = time.time()

def create_cached_context(
    api_key: str,
    upstream_url: str,
    model: str,
    system_instruction: str,
    ttl_minutes: int = 60
) -> Optional[str]:
    """
    Creates a cached context on the Gemini API side.

    Args:
        api_key: Gemini API key
        upstream_url: Gemini API URL
        model: Model name
        system_instruction: System instruction for caching
        ttl_minutes: Cache time-to-live in minutes (default 60)

    Returns:
        Cache ID or None on error
    """
    try:
        # Calculate hash of the system instruction for identification
        cache_key = hashlib.md5(f"{model}:{system_instruction}".encode()).hexdigest()

        # Check if cache already exists
        with _context_cache_lock:
            if cache_key in _cached_contexts:
                cached = _cached_contexts[cache_key]
                if not cached.is_expired():
                    cached.touch()
                    return cached.cache_id
                else:
                    # Remove expired cache
                    del _cached_contexts[cache_key]

        # Create new cache via Gemini API
        session = get_http_session()

        # TTL in seconds for API (minimum 60 seconds per documentation)
        ttl_seconds = max(60, ttl_minutes * 60)

        response = session.post(
            f"{upstream_url}/v1beta/cachedContents",
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": api_key
            },
            json={
                "model": f"models/{model}",
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "ttl": f"{ttl_seconds}s"
            },
            timeout=30
        )

        if response.status_code == 200:
            cache_data = response.json()
            cache_id = cache_data.get("name")

            if cache_id:
                # Save to local cache
                with _context_cache_lock:
                    _cached_contexts[cache_key] = CachedContext(
                        cache_id,
                        time.time(),
                        ttl_seconds
                    )

                return cache_id
        else:
            # Log error, but do not crash
            print(f"Failed to create cached context: {response.status_code} {response.text}")
            return None

    except Exception as e:
        print(f"Error creating cached context: {e}")
        return None

def get_cached_context_id(
    api_key: str,
    upstream_url: str,
    model: str,
    system_instruction: str
) -> Optional[str]:
    """
    Gets the cached context ID, creating it if necessary.

    Returns:
        Cache ID or None if caching is unavailable
    """
    cache_key = hashlib.md5(f"{model}:{system_instruction}".encode()).hexdigest()

    with _context_cache_lock:
        if cache_key in _cached_contexts:
            cached = _cached_contexts[cache_key]
            if not cached.is_expired():
                cached.touch()
                return cached.cache_id
            else:
                del _cached_contexts[cache_key]

    # Create new cache
    return create_cached_context(api_key, upstream_url, model, system_instruction)

def clear_expired_contexts():
    """Clears expired cached contexts"""
    with _context_cache_lock:
        expired = [
            key for key, cached in _cached_contexts.items()
            if cached.is_expired()
        ]
        for key in expired:
            del _cached_contexts[key]

# --- Cleanup function ---

def cleanup_resources():
    """Clears all optimization resources upon shutdown"""
    close_http_session()
    shutdown_tool_executor()
    clear_expired_contexts()
