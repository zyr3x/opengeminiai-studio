import os
import json
import asyncio
from typing import Dict, Any, List
import threading

from app.utils.core.mcp_handler import (
    BUILTIN_FUNCTIONS,
    execute_mcp_tool as sync_execute_mcp_tool
)

from app.utils.core.logging import log
from .optimization import (
    get_cached_tool_output,
    cache_tool_output,
    should_cache_tool
)

_async_context = threading.local()

async def execute_mcp_tool_async(function_name: str, tool_args: dict, project_root_override: str | None = None) -> str:
    log(f"🔧 Executing tool (async): {function_name} with args: {tool_args}")

    if should_cache_tool(function_name):
        cached_output = await get_cached_tool_output(function_name, tool_args)
        if cached_output is not None:
            log(f"✓ Cache hit for {function_name}")
            return cached_output

    try:
        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(
            None,
            sync_execute_mcp_tool,
            function_name,
            tool_args,
            project_root_override
        )

        if should_cache_tool(function_name):
            await cache_tool_output(function_name, tool_args, output)

        return output

    except Exception as e:
        error_msg = f"Error executing tool {function_name}: {str(e)}"
        log(error_msg)
        return json.dumps({"error": error_msg})

def _format_tool_response_part(function_name: str, output: str) -> Dict[str, Any]:
    response_payload = {}
    if output:
        try:
            response_payload = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            response_payload = {"content": str(output)}

    return {
        "functionResponse": {
            "name": function_name,
            "response": response_payload
        }
    }


async def execute_multiple_tools_async(
    tool_calls: List[Dict[str, Any]],
    project_root_override: str | None = None
) -> List[Dict[str, Any]]:
    from app.utils.core.optimization_utils import can_execute_parallel

    response_parts = []
    if can_execute_parallel(tool_calls):
        log(f"✓ Executing {len(tool_calls)} tools in parallel")

        tasks = [
            execute_mcp_tool_async(tc['name'], tc['args'], project_root_override)
            for tc in tool_calls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for tool_call, result in zip(tool_calls, results):
            function_name = tool_call['name']

            if isinstance(result, Exception):
                output = json.dumps({"error": str(result)})
            else:
                output = result

            response_parts.append(_format_tool_response_part(function_name, output))

    else:
        log(f"✓ Executing {len(tool_calls)} tools sequentially")

        for tool_call in tool_calls:
            function_name = tool_call['name']
            tool_args = tool_call['args']

            output = await execute_mcp_tool_async(function_name, tool_args, project_root_override)

            response_parts.append(_format_tool_response_part(function_name, output))

    return response_parts
