"""
Async MCP Tool Handling logic for Gemini-Proxy.
Provides async versions of tool execution for better concurrency.
"""
import os
import json
import asyncio
from typing import Dict, Any, List
import threading

# Import sync versions as fallback
from app.utils.flask.mcp_handler import (
    BUILTIN_FUNCTIONS,
    execute_mcp_tool as sync_execute_mcp_tool
)

from app.utils.core.logging import log
from .optimization import (
    get_cached_tool_output,
    cache_tool_output,
    should_cache_tool
)

# Thread-local storage for async context
_async_context = threading.local()

async def execute_mcp_tool_async(function_name: str, tool_args: dict, project_root_override: str | None = None) -> str:
    """
    Async version: Executes an MCP tool (built-in or external) and returns the result.
    Uses caching for read-only operations. All sync tool executions are run in a thread pool
    to avoid blocking the event loop.

    Args:
        function_name: The name of the function to call.
        tool_args: Dictionary of arguments for the tool function.
        project_root_override: Optional path to set as the project root for built-in tools.
    """
    log(f"🔧 Executing tool (async): {function_name} with args: {tool_args}")

    # Check cache first
    if should_cache_tool(function_name):
        cached_output = await get_cached_tool_output(function_name, tool_args)
        if cached_output is not None:
            log(f"✓ Cache hit for {function_name}")
            return cached_output

    # Execute the tool in an executor to avoid blocking the event loop
    try:
        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(
            None,
            sync_execute_mcp_tool,
            function_name,
            tool_args,
            project_root_override
        )
        
        # Cache the result if applicable
        if should_cache_tool(function_name):
            await cache_tool_output(function_name, tool_args, output)
        
        return output
        
    except Exception as e:
        error_msg = f"Error executing tool {function_name}: {str(e)}"
        log(error_msg)
        return json.dumps({"error": error_msg})

async def execute_external_mcp_tool_async(function_name: str, tool_args: dict) -> str:
    """
    Async version: Executes an external MCP tool via subprocess.
    """
    from app.utils.flask.mcp_handler import mcp_function_to_tool_map, mcp_config

    tool_name = mcp_function_to_tool_map.get(function_name)
    if not tool_name:
        return json.dumps({"error": f"Tool '{function_name}' is not registered to any MCP server."})

    # Find the MCP server configuration
    server_config = mcp_config.get("mcpServers", {}).get(tool_name)
    
    if not server_config:
        return json.dumps({"error": f"No MCP server found for tool: {function_name}"})
    
    command = server_config.get('command')
    args = server_config.get('args', [])
    env = server_config.get('env', {})
    
    if not command:
        return json.dumps({"error": "MCP server command not configured"})
    
    # Prepare the tool call request
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": function_name,
            "arguments": tool_args
        }
    }
    
    try:
        # Run subprocess asynchronously
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env}
        )
        
        # Send request and get response
        input_data = json.dumps(request).encode() + b'\n'
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=input_data),
            timeout=30.0
        )
        
        if stderr:
            log(f"MCP stderr: {stderr.decode()}")
        
        # Parse response
        if stdout:
            lines = stdout.decode().strip().split('\n')
            for line in lines:
                if line.strip():
                    try:
                        response = json.loads(line)
                        if 'result' in response:
                            result = response['result']
                            if isinstance(result, dict) and 'content' in result:
                                content = result['content']
                                if isinstance(content, list) and len(content) > 0:
                                    return content[0].get('text', json.dumps(result))
                            return json.dumps(result)
                        elif 'error' in response:
                            return json.dumps({"error": response['error']})
                    except json.JSONDecodeError:
                        continue
        
        return json.dumps({"error": "No valid response from MCP server"})
        
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Tool execution timed out after 30s"})
    except Exception as e:
        return json.dumps({"error": f"Failed to execute tool: {str(e)}"})

async def execute_multiple_tools_async(
    tool_calls: List[Dict[str, Any]],
    project_root_override: str | None = None
) -> List[Dict[str, Any]]:
    """
    Executes multiple tool calls in parallel when possible.

    Args:
        tool_calls: List of dicts with 'name' and 'args' keys
        project_root_override: Optional path to set as the project root for built-in tools.

    Returns:
        List of function response parts
    """
    from app.utils.core.optimization_utils import can_execute_parallel

    if can_execute_parallel(tool_calls):
        log(f"✓ Executing {len(tool_calls)} tools in parallel")

        # Execute all tools concurrently
        tasks = [
            execute_mcp_tool_async(tc['name'], tc['args'], project_root_override)
            for tc in tool_calls
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build response parts
        response_parts = []
        for tool_call, result in zip(tool_calls, results):
            function_name = tool_call['name']
            
            if isinstance(result, Exception):
                output = json.dumps({"error": str(result)})
            else:
                output = result
            
            # Parse output
            response_payload = {}
            if output:
                try:
                    response_payload = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    response_payload = {"content": str(output)}
            
            response_parts.append({
                "functionResponse": {
                    "name": function_name,
                    "response": response_payload
                }
            })
        
        return response_parts
    else:
        # Sequential execution
        log(f"✓ Executing {len(tool_calls)} tools sequentially")
        
        response_parts = []
        for tool_call in tool_calls:
            function_name = tool_call['name']
            tool_args = tool_call['args']
            
            output = await execute_mcp_tool_async(function_name, tool_args, project_root_override)
            
            response_payload = {}
            if output:
                try:
                    response_payload = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    response_payload = {"content": str(output)}
            
            response_parts.append({
                "functionResponse": {
                    "name": function_name,
                    "response": response_payload
                }
            })
        
        return response_parts
