import hashlib
import json
import re
from typing import List, Dict

MAX_TOOL_OUTPUT_TOKENS = 1000
MAX_FILE_PREVIEW_LINES = 50
MAX_DIFF_LINES = 100

def get_cache_key(function_name: str, tool_args: dict) -> str:
    args_str = json.dumps(tool_args, sort_keys=True, default=str)
    cache_string = f"{function_name}:{args_str}"
    return hashlib.md5(cache_string.encode()).hexdigest()

def should_cache_tool(function_name: str) -> bool:
    cacheable = [
        'list_files', 'get_file_content', 'list_symbols_in_file',
        'get_code_snippet', 'search_codebase', 'git_log', 'git_diff',
        'git_show', 'git_blame', 'list_recent_changes',
        'analyze_file_structure', 'get_file_stats'
    ]
    return function_name in cacheable

def estimate_tokens(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return int(len(text) / 3.5)

def can_execute_parallel(tool_calls: List[Dict]) -> bool:
    if len(tool_calls) <= 1:
        return False

    sequential_only = {'apply_patch', 'write_file', 'create_file', 'execute_command'}

    for tool_call in tool_calls:
        if tool_call.get('name') in sequential_only:
            return False

    return True

def estimate_token_count(contents: list) -> int:
    total_text = ""
    for item in contents:
        for part in item.get("parts", []):
            if "text" in part:
                total_text += part.get("text", "")
    return estimate_tokens(total_text)

def summarize_message(message: dict) -> str:
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

def optimize_code_output(code: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    tokens = estimate_tokens(code)

    if tokens <= max_tokens:
        return code

    lines = code.split('\n')
    total_lines = len(lines)

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
    tokens = estimate_tokens(diff)

    if tokens <= max_tokens:
        return diff

    lines = diff.split('\n')

    important_lines = []
    context_lines = []

    for i, line in enumerate(lines):
        if line.startswith(('+', '-', '@@', 'diff', 'index')):
            important_lines.append((i, line))
        elif line.strip():
            context_lines.append((i, line))

    max_lines = int((max_tokens * 3.5) / (len(diff) / len(lines)))

    if len(important_lines) <= max_lines:
        return diff

    result_lines = important_lines[:max_lines]
    total_lines = len(lines)
    shown_lines = len(result_lines)

    result = '\n'.join(line for _, line in result_lines)
    result += f"\n\n... [Showing {shown_lines} of {total_lines} lines] ...\n"

    return result

def optimize_list_output(text: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    tokens = estimate_tokens(text)

    if tokens <= max_tokens:
        return text

    lines = text.split('\n')
    total_lines = len(lines)

    max_lines = int((max_tokens * 3.5) / (len(text) / total_lines))

    if total_lines <= max_lines:
        return text

    result = '\n'.join(lines[:max_lines])
    result += f"\n... [Showing {max_lines} of {total_lines} items] ..."

    return result

def optimize_tool_output(output: str, function_name: str) -> str:
    if not output or not isinstance(output, str):
        return output

    tokens = estimate_tokens(output)

    if tokens <= MAX_TOOL_OUTPUT_TOKENS:
        return output

    if '```diff' in output or 'git diff' in output.lower():
        return optimize_diff_output(output)

    elif '```' in output:
        code_match = re.search(r'```[\w]*\n(.*?)\n```', output, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            optimized_code = optimize_code_output(code)
            return output.replace(code, optimized_code)
        return optimize_code_output(output)

    elif function_name in ['list_files', 'list_recent_changes', 'list_symbols_in_file']:
        return optimize_list_output(output)

    else:
        max_chars = MAX_TOOL_OUTPUT_TOKENS * 4
        if len(output) > max_chars:
            return output[:max_chars] + f"\n\n... [Output truncated from {len(output)} to {max_chars} chars]"

    return output

def smart_truncate_contents(contents: list, limit: int, keep_recent: int = 5) -> list:
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
