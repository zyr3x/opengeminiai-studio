"""
Core optimization module to reduce token usage and improve performance.
"""
import hashlib
import json
import time
import threading
from typing import Optional, List, Dict
from datetime import date
from app.db import get_db_connection
from functools import wraps
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_tool_output_cache = {}
_cache_lock = threading.Lock()
from app.utils.core.optimization_utils import get_cache_key

CACHE_TTL = 300
CACHE_MAX_SIZE = 100

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

        if len(_tool_output_cache) > CACHE_MAX_SIZE:
            sorted_items = sorted(
                _tool_output_cache.items(),
                key=lambda x: x[1][1]
            )
            _tool_output_cache = dict(sorted_items[-CACHE_MAX_SIZE:])

def get_cached_tool_output(function_name: str, tool_args: dict) -> Optional[str]:
    """Gets result from cache if present and not expired"""
    clean_cache()

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

            cursor.execute("""
                UPDATE token_usage
                SET input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?
                WHERE date = ? AND key_hash = ? AND model_name = ?
            """, (input_tokens, output_tokens, today, key_hash, model_name))

            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO token_usage (date, key_hash, model_name, input_tokens, output_tokens)
                    VALUES (?, ?, ?, ?, ?)
                """, (today, key_hash, model_name, input_tokens, output_tokens))

            conn.commit()
        except Exception as e:
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

_metrics_lock = threading.Lock()
_metrics = {
    'cache_hits': 0,
    'cache_misses': 0,
    'tokens_saved': 0,
    'requests_optimized': 0,
    'tool_calls_total': 0,
    'tool_calls_external': 0,
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

    reset_token_stats()

    with _cache_lock:
        _tool_output_cache.clear()

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
            if _http_session is None:
                session = requests.Session()

                retry_strategy = Retry(
                    total=2,
                    status_forcelist=[429, 502, 503, 504],
                    backoff_factor=10,
                    allowed_methods=["GET", "POST"],
                    respect_retry_after_header=True
                )

                adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=retry_strategy,
                    pool_block=False
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

                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()

                if len(self.calls) >= self.max_calls:
                    sleep_time = self.period - (now - self.calls[0]) + 0.01
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        now = time.time()
                        while self.calls and now - self.calls[0] >= self.period:
                            self.calls.popleft()

                self.calls.append(time.time())

            return func(*args, **kwargs)

        return wrapper

    def wait_if_needed(self):
        """Waits if rate limit is reached (without executing function)"""
        with self.lock:
            now = time.time()

            while self.calls and now - self.calls[0] >= self.period:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0]) + 0.01
                if sleep_time > 0:
                    time.sleep(sleep_time)

_gemini_rate_limiter = None

def get_rate_limiter(max_calls: int = 60, period: int = 60) -> RateLimiter:
    """Returns the global rate limiter"""
    global _gemini_rate_limiter
    if _gemini_rate_limiter is None:
        _gemini_rate_limiter = RateLimiter(max_calls, period)
    return _gemini_rate_limiter

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
        cache_key = hashlib.md5(f"{model}:{system_instruction}".encode()).hexdigest()

        with _context_cache_lock:
            if cache_key in _cached_contexts:
                cached = _cached_contexts[cache_key]
                if not cached.is_expired():
                    cached.touch()
                    return cached.cache_id
                else:
                    del _cached_contexts[cache_key]

        session = get_http_session()

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
                with _context_cache_lock:
                    _cached_contexts[cache_key] = CachedContext(
                        cache_id,
                        time.time(),
                        ttl_seconds
                    )

                return cache_id
        else:
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

def cleanup_resources():
    """Clears all optimization resources upon shutdown"""
    close_http_session()
    shutdown_tool_executor()
    clear_expired_contexts()
