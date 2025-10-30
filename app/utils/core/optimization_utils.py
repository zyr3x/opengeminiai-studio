import hashlib
import json
from typing import List, Dict

# --- Optimization Constants ---
MAX_TOOL_OUTPUT_TOKENS = 1000
MAX_FILE_PREVIEW_LINES = 50
MAX_DIFF_LINES = 100

def get_cache_key(function_name: str, tool_args: dict) -> str:
    """Generates a cache key for the tool"""
    args_str = json.dumps(tool_args, sort_keys=True, default=str)
    cache_string = f"{function_name}:{args_str}"
    return hashlib.md5(cache_string.encode()).hexdigest()

def should_cache_tool(function_name: str) -> bool:
    """Determines whether to cache the results of this tool."""
    cacheable = [
        'list_files', 'get_file_content', 'list_symbols_in_file',
        'get_code_snippet', 'search_codebase', 'git_log', 'git_diff',
        'git_show', 'git_blame', 'list_recent_changes',
        'analyze_file_structure', 'get_file_stats'
    ]
    return function_name in cacheable

def estimate_tokens(text: str) -> int:
    """
    Estimates token count for a string.
    A common heuristic is that 1 token is roughly 4 characters for English text.
    We use 3.5 for a more conservative estimate with code/mixed content.
    """
    if not isinstance(text, str):
        return 0
    return int(len(text) / 3.5)

def can_execute_parallel(tool_calls: List[Dict]) -> bool:
    """
    Determines if tool calls can be executed in parallel.
    Some tools that modify state must be executed sequentially.
    """
    if len(tool_calls) <= 1:
        return False

    sequential_only = {'apply_patch', 'write_file', 'create_file', 'execute_command'}

    for tool_call in tool_calls:
        if tool_call.get('name') in sequential_only:
            return False

    return True

def estimate_token_count(contents: list) -> int:
    """
    Estimates the token count of the 'contents' list by summing up text parts.
    """
    total_text = ""
    for item in contents:
        for part in item.get("parts", []):
            if "text" in part:
                total_text += part.get("text", "")
    return estimate_tokens(total_text)

def summarize_message(message: dict) -> str:
    """Creates a brief summary of the message"""
    role = message.get('role', 'unknown')
    parts = message.get('parts', [])

    text_parts = []
    for part in parts:
        if 'text' in part:
            text_parts.append(part['text'])

    full_text = ' '.join(text_parts)

    max_summary_length = 100
    if len(full_text) > max_summary_length:
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
    tokens = estimate_token_count(contents)

    if tokens <= limit:
        return contents

    if len(contents) <= keep_recent + 1:
        return contents

    result = [contents[0]]

    recent_messages = contents[-keep_recent:]

    middle_messages = contents[1:-keep_recent]

    if middle_messages:
        summaries = [summarize_message(msg) for msg in middle_messages]
        summary_text = "Previous conversation summary:\n" + "\n".join(summaries)

        result.append({
            "role": "user",
            "parts": [{"text": summary_text}]
        })

    result.extend(recent_messages)

    new_tokens = estimate_token_count(result)

    if new_tokens > limit:
        if keep_recent > 2:
            return smart_truncate_contents(contents, limit, keep_recent - 1)
        else:
            return result[:1] + result[-2:]

    return result
