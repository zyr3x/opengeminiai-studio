"""
Async MCP Tool Handling logic for Gemini-Proxy.
Provides async versions of tool execution for better concurrency.
"""
import os
import json
import asyncio
import subprocess
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
import threading

# Import sync versions as fallback
from .mcp_handler import (
    BUILTIN_FUNCTIONS,
    get_project_root,
    set_project_root,
    execute_mcp_tool as sync_execute_mcp_tool,
    create_tool_declarations,
    create_tool_declarations_from_list,
    disable_all_mcp_tools
)

from .async_utils import log
from .async_optimization import (
    get_cached_tool_output,
    cache_tool_output,
    should_cache_tool
)

# Thread-local storage for async context
_async_context = threading.local()

async def execute_mcp_tool_async(function_name: str, tool_args: dict) -> str:
    """
    Async version: Executes an MCP tool (built-in or external) and returns the result.
    Uses caching for read-only operations.
    """
    log(f"🔧 Executing tool (async): {function_name} with args: {tool_args}")
    
    # Check cache first
    if should_cache_tool(function_name):
        cached_output = await get_cached_tool_output(function_name, tool_args)
        if cached_output is not None:
            log(f"✓ Cache hit for {function_name}")
            return cached_output
    
    # Execute the tool
    try:
        # Check if it's a built-in function
        if function_name in BUILTIN_FUNCTIONS:
            # Built-in functions are sync, run in executor
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                sync_execute_mcp_tool,
                function_name,
                tool_args
            )
        else:
            # External MCP tool - run process async
            output = await execute_external_mcp_tool_async(function_name, tool_args)
        
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
    from .mcp_handler import mcp_servers
    
    # Find the MCP server configuration
    server_config = None
    for server_name, config in mcp_servers.items():
        tools = config.get('tools', [])
        if any(tool.get('name') == function_name for tool in tools):
            server_config = config
            break
    
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
    tool_calls: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Executes multiple tool calls in parallel when possible.
    
    Args:
        tool_calls: List of dicts with 'name' and 'args' keys
    
    Returns:
        List of function response parts
    """
    from .async_optimization import can_execute_parallel
    
    if can_execute_parallel(tool_calls):
        log(f"✓ Executing {len(tool_calls)} tools in parallel")
        
        # Execute all tools concurrently
        tasks = [
            execute_mcp_tool_async(tc['name'], tc['args'])
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
            
            output = await execute_mcp_tool_async(function_name, tool_args)
            
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
