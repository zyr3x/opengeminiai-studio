from typing import List, Dict

# --- Optimization Constants ---
MAX_TOOL_OUTPUT_TOKENS = 1000
MAX_FILE_PREVIEW_LINES = 50
MAX_DIFF_LINES = 100

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
