from app.utils.core.optimization import *
from typing import List, Dict, Tuple
from concurrent.futures import as_completed

def execute_tools_parallel(tool_calls: List[Dict], project_root_override: str | None = None) -> List[Tuple[Dict, str]]:
    """
    Executes multiple tool calls in parallel using a thread pool.

    Args:
        tool_calls: List of dictionaries with 'name' and 'args'
        project_root_override: The project root path to be used by all tool calls in this batch.

    Returns:
        List of tuples (tool_call, result)
    """
    if not tool_calls:
        return []

    from app.utils.flask import mcp_handler

    executor = get_tool_executor()
    futures = {}

    for tool_call in tool_calls:
        future = executor.submit(
            mcp_handler.execute_mcp_tool,
            tool_call.get('name'),
            tool_call.get('args', {}),
            project_root_override
        )
        futures[future] = tool_call

    results = []
    for future in as_completed(futures):
        tool_call = futures[future]
        try:
            result = future.result(timeout=120)
            results.append((tool_call, result))
        except Exception as e:
            error_msg = f"Error executing {tool_call.get('name')}: {e}"
            results.append((tool_call, error_msg))

    return results
