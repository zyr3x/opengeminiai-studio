"""
Модуль оптимизации для снижения использования токенов и повышения производительности.
ФАЗА 1: Кэширование, оптимизация вывода, умное усечение
ФАЗА 2: Connection pooling, rate limiting, prompt caching, parallel execution
"""
import hashlib
import json
import time
import re
import threading
from typing import Optional, Tuple, List, Dict
from functools import lru_cache, wraps
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Кэш для результатов инструментов ---
_tool_output_cache = {}
CACHE_TTL = 300  # 5 минут
CACHE_MAX_SIZE = 100  # Максимум записей в кэше

# --- Константы для оптимизации ---
MAX_TOOL_OUTPUT_TOKENS = 1000  # Максимальный размер вывода инструмента
MAX_FILE_PREVIEW_LINES = 50    # Максимум строк для preview файла
MAX_DIFF_LINES = 100           # Максимум строк для diff

def clean_cache():
    """Очищает устаревшие записи из кэша"""
    global _tool_output_cache
    now = time.time()
    expired_keys = [
        key for key, (_, timestamp) in _tool_output_cache.items()
        if now - timestamp > CACHE_TTL
    ]
    for key in expired_keys:
        del _tool_output_cache[key]
    
    # Если кэш слишком большой, удаляем самые старые записи
    if len(_tool_output_cache) > CACHE_MAX_SIZE:
        sorted_items = sorted(
            _tool_output_cache.items(),
            key=lambda x: x[1][1]  # Сортируем по timestamp
        )
        # Оставляем только CACHE_MAX_SIZE самых свежих
        _tool_output_cache = dict(sorted_items[-CACHE_MAX_SIZE:])

def get_cache_key(function_name: str, tool_args: dict) -> str:
    """Генерирует ключ кэша для инструмента"""
    # Сортируем ключи для стабильности хеша
    args_str = json.dumps(tool_args, sort_keys=True, default=str)
    cache_string = f"{function_name}:{args_str}"
    return hashlib.md5(cache_string.encode()).hexdigest()

def get_cached_tool_output(function_name: str, tool_args: dict) -> Optional[str]:
    """Получает результат из кэша если он есть и не устарел"""
    clean_cache()  # Периодически чистим кэш
    
    cache_key = get_cache_key(function_name, tool_args)
    
    if cache_key in _tool_output_cache:
        output, timestamp = _tool_output_cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            return output
    
    return None

def cache_tool_output(function_name: str, tool_args: dict, output: str):
    """Сохраняет результат инструмента в кэш"""
    cache_key = get_cache_key(function_name, tool_args)
    _tool_output_cache[cache_key] = (output, time.time())

def should_cache_tool(function_name: str) -> bool:
    """Определяет, нужно ли кэшировать результаты этого инструмента"""
    # Не кэшируем изменяющие операции
    non_cacheable = ['apply_patch', 'git_status']
    
    # Кэшируем операции чтения
    cacheable = [
        'list_files', 'get_file_content', 'list_symbols_in_file',
        'get_code_snippet', 'search_codebase', 'git_log', 'git_diff',
        'git_show', 'git_blame', 'list_recent_changes',
        'analyze_file_structure', 'get_file_stats'
    ]
    
    return function_name in cacheable

# --- Оптимизация вывода инструментов ---

def estimate_tokens(text: str) -> int:
    """Улучшенная оценка количества токенов"""
    # Более точная формула с учетом пробелов и специальных символов
    # Примерно 3.5 символа на токен для смешанного текста
    return int(len(text) / 3.5)

def optimize_code_output(code: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Оптимизирует вывод кода"""
    tokens = estimate_tokens(code)
    
    if tokens <= max_tokens:
        return code
    
    lines = code.split('\n')
    total_lines = len(lines)
    
    # Показываем начало и конец файла
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
    """Оптимизирует вывод git diff"""
    tokens = estimate_tokens(diff)
    
    if tokens <= max_tokens:
        return diff
    
    lines = diff.split('\n')
    
    # Для diff приоритет - измененные строки (+ и -)
    important_lines = []
    context_lines = []
    
    for i, line in enumerate(lines):
        if line.startswith(('+', '-', '@@', 'diff', 'index')):
            important_lines.append((i, line))
        elif line.strip():  # Контекстные строки
            context_lines.append((i, line))
    
    # Берем все важные строки и немного контекста
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
    """Оптимизирует вывод списков файлов"""
    tokens = estimate_tokens(text)
    
    if tokens <= max_tokens:
        return text
    
    lines = text.split('\n')
    total_lines = len(lines)
    
    # Для списков - показываем начало
    max_lines = int((max_tokens * 3.5) / (len(text) / total_lines))
    
    if total_lines <= max_lines:
        return text
    
    result = '\n'.join(lines[:max_lines])
    result += f"\n... [Showing {max_lines} of {total_lines} items] ..."
    
    return result

def optimize_tool_output(output: str, function_name: str) -> str:
    """
    Интеллектуально оптимизирует вывод инструмента для снижения использования токенов.
    """
    if not output or not isinstance(output, str):
        return output
    
    tokens = estimate_tokens(output)
    
    # Если вывод маленький, не трогаем
    if tokens <= MAX_TOOL_OUTPUT_TOKENS:
        return output
    
    # Определяем тип вывода и применяем соответствующую стратегию
    if '```diff' in output or 'git diff' in output.lower():
        return optimize_diff_output(output)
    
    elif '```' in output:  # Блок кода
        # Извлекаем код между ```
        code_match = re.search(r'```[\w]*\n(.*?)\n```', output, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            optimized_code = optimize_code_output(code)
            return output.replace(code, optimized_code)
        return optimize_code_output(output)
    
    elif function_name in ['list_files', 'list_recent_changes', 'list_symbols_in_file']:
        return optimize_list_output(output)
    
    else:
        # Общее усечение для других типов
        max_chars = MAX_TOOL_OUTPUT_TOKENS * 4
        if len(output) > max_chars:
            return output[:max_chars] + f"\n\n... [Output truncated from {len(output)} to {max_chars} chars]"
    
    return output

# --- Интеллектуальное сжатие истории ---

def summarize_message(message: dict) -> str:
    """Создает краткое резюме сообщения"""
    role = message.get('role', 'unknown')
    parts = message.get('parts', [])
    
    # Извлекаем текст
    text_parts = []
    for part in parts:
        if 'text' in part:
            text_parts.append(part['text'])
    
    full_text = ' '.join(text_parts)
    
    # Ограничиваем длину резюме
    max_summary_length = 100
    if len(full_text) > max_summary_length:
        # Берем первые слова
        words = full_text.split()
        summary = ' '.join(words[:15]) + '...'
    else:
        summary = full_text
    
    return f"[{role}]: {summary}"

def smart_truncate_contents(contents: list, limit: int, keep_recent: int = 5) -> list:
    """
    Интеллектуально сжимает историю сообщений вместо удаления.
    Сохраняет системный промпт, последние N сообщений, и создает краткое резюме остальных.
    """
    from app.utils import estimate_token_count
    
    tokens = estimate_token_count(contents)
    
    if tokens <= limit:
        return contents
    
    if len(contents) <= keep_recent + 1:
        # Слишком мало сообщений, просто обрезаем
        return contents[:1] + contents[-(keep_recent-1):]
    
    # Всегда сохраняем системный промпт (первое сообщение)
    result = [contents[0]]
    
    # Последние keep_recent сообщений тоже сохраняем
    recent_messages = contents[-keep_recent:]
    
    # Средние сообщения сжимаем в краткое резюме
    middle_messages = contents[1:-keep_recent]
    
    if middle_messages:
        summaries = [summarize_message(msg) for msg in middle_messages]
        summary_text = "Previous conversation summary:\n" + "\n".join(summaries)
        
        result.append({
            "role": "user",
            "parts": [{"text": summary_text}]
        })
    
    # Добавляем последние сообщения
    result.extend(recent_messages)
    
    # Проверяем, уместились ли мы в лимит
    new_tokens = estimate_token_count(result)
    
    if new_tokens > limit:
        # Если все еще не умещаемся, уменьшаем keep_recent
        if keep_recent > 2:
            return smart_truncate_contents(contents, limit, keep_recent - 1)
        else:
            # Последняя мера - обычное усечение
            return result[:1] + result[-2:]
    
    return result

# --- Статистика и метрики ---

_metrics = {
    'cache_hits': 0,
    'cache_misses': 0,
    'tokens_saved': 0,
    'requests_optimized': 0
}

def record_cache_hit():
    """Записывает попадание в кэш"""
    _metrics['cache_hits'] += 1

def record_cache_miss():
    """Записывает промах кэша"""
    _metrics['cache_misses'] += 1

def record_tokens_saved(count: int):
    """Записывает сэкономленные токены"""
    _metrics['tokens_saved'] += count

def record_optimization():
    """Записывает оптимизированный запрос"""
    _metrics['requests_optimized'] += 1

def get_metrics() -> dict:
    """Возвращает метрики оптимизации"""
    total_cache_requests = _metrics['cache_hits'] + _metrics['cache_misses']
    cache_hit_rate = (_metrics['cache_hits'] / total_cache_requests * 100) if total_cache_requests > 0 else 0
    
    return {
        **_metrics,
        'cache_hit_rate': f"{cache_hit_rate:.1f}%",
        'cache_size': len(_tool_output_cache)
    }

def reset_metrics():
    """Сбрасывает метрики"""
    global _metrics
    _metrics = {
        'cache_hits': 0,
        'cache_misses': 0,
        'tokens_saved': 0,
        'requests_optimized': 0
    }

# ============================================================================
# ФАЗА 2: ПРОДВИНУТАЯ ОПТИМИЗАЦИЯ
# ============================================================================

# --- Connection Pooling ---

_http_session = None
_session_lock = threading.Lock()

def get_http_session() -> requests.Session:
    """
    Возвращает настроенную HTTP сессию с connection pooling и retry стратегией.
    Переиспользует соединения для повышения производительности.
    """
    global _http_session
    
    if _http_session is None:
        with _session_lock:
            # Double-check locking pattern
            if _http_session is None:
                session = requests.Session()
                
                # Настройка retry стратегии
                retry_strategy = Retry(
                    total=3,
                    status_forcelist=[429, 500, 502, 503, 504],
                    backoff_factor=1,
                    allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
                )
                
                # Адаптер с connection pooling
                adapter = HTTPAdapter(
                    pool_connections=10,    # Количество connection pools
                    pool_maxsize=20,        # Максимум соединений в пуле
                    max_retries=retry_strategy,
                    pool_block=False        # Не блокировать при достижении лимита
                )
                
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                
                _http_session = session
    
    return _http_session

def close_http_session():
    """Закрывает HTTP сессию (вызывается при shutdown)"""
    global _http_session
    if _http_session is not None:
        _http_session.close()
        _http_session = None

# --- Rate Limiting ---

class RateLimiter:
    """
    Thread-safe rate limiter для ограничения частоты запросов.
    Использует sliding window алгоритм.
    """
    def __init__(self, max_calls: int, period: int):
        """
        Args:
            max_calls: Максимальное количество вызовов
            period: Период в секундах
        """
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = threading.Lock()
    
    def __call__(self, func):
        """Декоратор для применения rate limiting"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.lock:
                now = time.time()
                
                # Удаляем старые вызовы (за пределами окна)
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                
                # Если достигнут лимит, ждем
                if len(self.calls) >= self.max_calls:
                    sleep_time = self.period - (now - self.calls[0]) + 0.01
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        now = time.time()
                        # Очищаем старые после sleep
                        while self.calls and now - self.calls[0] >= self.period:
                            self.calls.popleft()
                
                # Добавляем текущий вызов
                self.calls.append(time.time())
            
            return func(*args, **kwargs)
        
        return wrapper
    
    def wait_if_needed(self):
        """Ожидает если достигнут rate limit (без выполнения функции)"""
        with self.lock:
            now = time.time()
            
            # Удаляем старые вызовы
            while self.calls and now - self.calls[0] >= self.period:
                self.calls.popleft()
            
            # Если достигнут лимит, ждем
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0]) + 0.01
                if sleep_time > 0:
                    time.sleep(sleep_time)

# Глобальный rate limiter для Gemini API
# По умолчанию: 60 запросов в минуту (можно настроить через env)
_gemini_rate_limiter = None

def get_rate_limiter(max_calls: int = 60, period: int = 60) -> RateLimiter:
    """Возвращает глобальный rate limiter"""
    global _gemini_rate_limiter
    if _gemini_rate_limiter is None:
        _gemini_rate_limiter = RateLimiter(max_calls, period)
    return _gemini_rate_limiter

# --- Parallel Tool Execution ---

_tool_executor = None
_executor_lock = threading.Lock()

def get_tool_executor(max_workers: int = 5) -> ThreadPoolExecutor:
    """
    Возвращает thread pool executor для параллельного выполнения инструментов.
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
    """Завершает thread pool executor"""
    global _tool_executor
    if _tool_executor is not None:
        _tool_executor.shutdown(wait=True)
        _tool_executor = None

def execute_tools_parallel(tool_calls: List[Dict]) -> List[Tuple[Dict, str]]:
    """
    Выполняет несколько tool calls параллельно.
    
    Args:
        tool_calls: Список словарей с 'name' и 'args'
    
    Returns:
        Список кортежей (tool_call, result)
    """
    if not tool_calls:
        return []
    
    # Импортируем здесь чтобы избежать циклических зависимостей
    from app import mcp_handler
    
    executor = get_tool_executor()
    futures = {}
    
    # Запускаем все tool calls параллельно
    for tool_call in tool_calls:
        future = executor.submit(
            mcp_handler.execute_mcp_tool,
            tool_call.get('name'),
            tool_call.get('args', {})
        )
        futures[future] = tool_call
    
    # Собираем результаты по мере готовности
    results = []
    for future in as_completed(futures):
        tool_call = futures[future]
        try:
            result = future.result(timeout=120)  # 2 минуты на tool
            results.append((tool_call, result))
        except Exception as e:
            error_msg = f"Error executing {tool_call.get('name')}: {e}"
            results.append((tool_call, error_msg))
    
    return results

def can_execute_parallel(tool_calls: List[Dict]) -> bool:
    """
    Определяет, можно ли выполнить tool calls параллельно.
    Некоторые инструменты должны выполняться последовательно (например, apply_patch).
    """
    # Инструменты, которые нельзя выполнять параллельно
    sequential_only = {'apply_patch'}
    
    # Если есть хотя бы один последовательный инструмент, выполняем все последовательно
    for tool_call in tool_calls:
        if tool_call.get('name') in sequential_only:
            return False
    
    # Можно выполнять параллельно если больше одного инструмента
    return len(tool_calls) > 1

# --- Prompt Caching (Gemini Context Caching API) ---

_cached_contexts = {}
_context_cache_lock = threading.Lock()

class CachedContext:
    """Представляет кэшированный контекст на стороне Gemini"""
    def __init__(self, cache_id: str, created_at: float, ttl: int = 3600):
        self.cache_id = cache_id
        self.created_at = created_at
        self.ttl = ttl
        self.last_used = created_at
    
    def is_expired(self) -> bool:
        """Проверяет, истек ли кэш"""
        return time.time() - self.created_at > self.ttl
    
    def touch(self):
        """Обновляет время последнего использования"""
        self.last_used = time.time()

def create_cached_context(
    api_key: str,
    upstream_url: str,
    model: str,
    system_instruction: str,
    ttl_minutes: int = 60
) -> Optional[str]:
    """
    Создает кэшированный контекст на стороне Gemini API.
    
    Args:
        api_key: API ключ Gemini
        upstream_url: URL Gemini API
        model: Название модели
        system_instruction: Системная инструкция для кэширования
        ttl_minutes: Время жизни кэша в минутах (по умолчанию 60)
    
    Returns:
        Cache ID или None при ошибке
    """
    try:
        # Вычисляем хеш системной инструкции для идентификации
        cache_key = hashlib.md5(f"{model}:{system_instruction}".encode()).hexdigest()
        
        # Проверяем, есть ли уже кэш
        with _context_cache_lock:
            if cache_key in _cached_contexts:
                cached = _cached_contexts[cache_key]
                if not cached.is_expired():
                    cached.touch()
                    return cached.cache_id
                else:
                    # Удаляем истекший кэш
                    del _cached_contexts[cache_key]
        
        # Создаем новый кэш через Gemini API
        session = get_http_session()
        
        # TTL в секундах для API (минимум 60 секунд по документации)
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
                # Сохраняем в локальном кэше
                with _context_cache_lock:
                    _cached_contexts[cache_key] = CachedContext(
                        cache_id,
                        time.time(),
                        ttl_seconds
                    )
                
                return cache_id
        else:
            # Логируем ошибку, но не падаем
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
    Получает ID кэшированного контекста, создавая его при необходимости.
    
    Returns:
        Cache ID или None если кэширование недоступно
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
    
    # Создаем новый кэш
    return create_cached_context(api_key, upstream_url, model, system_instruction)

def clear_expired_contexts():
    """Очищает истекшие кэшированные контексты"""
    with _context_cache_lock:
        expired = [
            key for key, cached in _cached_contexts.items()
            if cached.is_expired()
        ]
        for key in expired:
            del _cached_contexts[key]

# --- Cleanup функция ---

def cleanup_resources():
    """Очищает все ресурсы оптимизации при shutdown"""
    close_http_session()
    shutdown_tool_executor()
    clear_expired_contexts()
