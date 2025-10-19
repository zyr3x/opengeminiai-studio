"""
MCP Tool Handling logic for Gemini-Proxy.
"""
import os
import json
import subprocess
import shlex
import select
import time

from .utils import log

# --- MCP Tool Configuration ---
mcp_config = {}
MCP_CONFIG_FILE = 'var/config/mcp.json'
mcp_function_declarations = []  # A flat list of all function declarations from all tools
mcp_function_to_tool_map = {}   # Maps a function name to its parent tool name (from mcpServers)
mcp_function_input_schema_map = {}  # Maps a function name to its inputSchema from MCP
mcp_tool_processes = {}  # Cache for running tool subprocesses
mcp_request_id_counter = 1  # Counter for unique JSON-RPC request IDs

MAX_FUNCTION_DECLARATIONS_DEFAULT = 64 # Default documented limit
max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT # Configurable limit

DISABLE_ALL_MCP_TOOLS_DEFAULT = False
disable_all_mcp_tools = DISABLE_ALL_MCP_TOOLS_DEFAULT # Global flag to disable all MCP tools

def set_disable_all_mcp_tools(status: bool):
    """Sets the global status for disabling all MCP tools and saves it to config."""
    global disable_all_mcp_tools, mcp_config
    disable_all_mcp_tools = status
    # Update the in-memory config and save it
    mcp_config["disableAllTools"] = status
    try:
        with open(MCP_CONFIG_FILE, 'w') as f:
            json.dump(mcp_config, f, indent=2)
        log(f"MCP general settings updated and saved to {MCP_CONFIG_FILE}. Disable all tools: {status}")
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error saving MCP config: {e}")


def get_declarations_from_tool(tool_name, tool_info):
    """Fetches function declaration schema(s) from an MCP tool using MCP protocol."""
    global mcp_function_input_schema_map
    command = [tool_info["command"]] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        log(f"Fetching schema for tool '{tool_name}'...")

        # Send MCP initialization and tools/list request
        mcp_init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gemini-proxy", "version": "1.0.0"}
            }
        }

        tools_list_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        # Send initialize -> notifications/initialized -> tools/list in a single stdio session
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        input_data = (
            json.dumps(mcp_init_request) + "\n" +
            json.dumps(initialized_notification) + "\n" +
            json.dumps(tools_list_request) + "\n"
        )

        process = subprocess.run(
            command,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=30
        )

        if process.returncode != 0:
            print(f"MCP tool '{tool_name}' failed with exit code {process.returncode}")
            if process.stderr:
                print(f"Stderr: {process.stderr}")
            return []

        # Parse MCP response - look for tools/list response (id == 1)
        lines = process.stdout.strip().split('\n')
        tools = []

        for line in lines:
            if not line.strip():
                continue
            try:
                if line.startswith('\ufeff'):
                    line = line.lstrip('\ufeff')
                response = json.loads(line)
                if (response.get("id") == 1 and
                    "result" in response and
                    "tools" in response["result"]):
                    mcp_tools = response["result"]["tools"]

                    # Convert MCP tool format to Gemini function declarations
                    for tool in mcp_tools:
                        declaration = {
                            "name": tool["name"],
                            "description": tool.get("description", f"Execute {tool['name']} tool")
                        }
                        # Cache original inputSchema for later argument coercion
                        mcp_function_input_schema_map[tool["name"]] = tool.get("inputSchema")

                        # Convert MCP input schema to Gemini parameters format
                        if "inputSchema" in tool:
                            schema = tool["inputSchema"]
                            if schema.get("type") == "object":
                                # Use Gemini function schema types (uppercase)
                                declaration["parameters"] = {
                                    "type": "OBJECT",
                                    "properties": {}
                                }

                                def convert_property_to_gemini(prop_def):
                                    """Convert a JSON Schema property to Gemini function parameter format."""
                                    t = str(prop_def.get("type", "string")).lower()

                                    if t == "string":
                                        return {
                                            "type": "STRING",
                                            "description": prop_def.get("description", "String parameter")
                                        }
                                    elif t in ("number", "integer"):
                                        return {
                                            "type": "NUMBER",
                                            "description": prop_def.get("description", "Number parameter")
                                        }
                                    elif t == "boolean":
                                        return {
                                            "type": "BOOLEAN",
                                            "description": prop_def.get("description", "Boolean parameter")
                                        }
                                    elif t == "array":
                                        param = {
                                            "type": "ARRAY",
                                            "description": prop_def.get("description", "Array parameter")
                                        }
                                        # Handle array items - required for Gemini API
                                        items = prop_def.get("items", {})
                                        if items:
                                            param["items"] = convert_property_to_gemini(items)
                                        else:
                                            # Default to string items if not specified
                                            param["items"] = {"type": "STRING"}
                                        return param
                                    elif t == "object":
                                        param = {
                                            "type": "OBJECT",
                                            "description": prop_def.get("description", "Object parameter")
                                        }
                                        # Handle nested object properties
                                        if "properties" in prop_def:
                                            param["properties"] = {}
                                            for nested_name, nested_def in prop_def["properties"].items():
                                                param["properties"][nested_name] = convert_property_to_gemini(nested_def)
                                        return param
                                    else:
                                        return {
                                            "type": "STRING",
                                            "description": prop_def.get("description", "String parameter")
                                        }

                                for prop_name, prop_def in schema.get("properties", {}).items():
                                    declaration["parameters"]["properties"][prop_name] = convert_property_to_gemini(prop_def)

                                if "required" in schema:
                                    declaration["parameters"]["required"] = schema["required"]

                        tools.append(declaration)
                    break
            except json.JSONDecodeError:
                continue

        if process.stderr:
            print(f"Stderr: {process.stderr}")

        log(f"Successfully fetched {len(tools)} function declaration(s) for tool '{tool_name}'.")
        return tools

    except subprocess.TimeoutExpired:
        print(f"Error: Timeout while fetching schema for tool '{tool_name}'.")
    except Exception as e:
        print(f"An unexpected error occurred while fetching schema for tool '{tool_name}': {e}")

    return []

def fetch_mcp_tool_list(tool_info):
    """Fetches the raw list of tools from an MCP server based on its config."""
    command_str = tool_info.get("command")
    if not command_str:
        return {"error": "Command not provided."}

    command = [command_str] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        log(f"Fetching tool list for command: '{command_str}'")

        mcp_init_request = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gemini-proxy", "version": "1.0.0"}}
        }
        tools_list_request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
        }
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        input_data = (
            json.dumps(mcp_init_request) + "\n" +
            json.dumps(initialized_notification) + "\n" +
            json.dumps(tools_list_request) + "\n"
        )

        process = subprocess.run(
            command, input=input_data, text=True, capture_output=True,
            check=False, env=env, timeout=30
        )

        if process.returncode != 0:
            return {"error": f"Tool failed with exit code {process.returncode}", "stderr": process.stderr.strip()}

        lines = process.stdout.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            try:
                if line.startswith('\ufeff'):
                    line = line.lstrip('\ufeff')
                response = json.loads(line)
                if response.get("id") == 1 and "result" in response and "tools" in response["result"]:
                    return {"tools": response["result"]["tools"]}
            except json.JSONDecodeError:
                continue

        return {"error": "Did not receive a valid tools/list response.", "stdout": process.stdout.strip(), "stderr": process.stderr.strip()}

    except subprocess.TimeoutExpired:
        return {"error": "Timeout while fetching tool list."}
    except FileNotFoundError:
        return {"error": f"Command not found: '{command_str}'."}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}

def load_mcp_config():
    """Loads MCP tool configuration from file and fetches schemas for all configured tools."""
    global mcp_config, mcp_function_declarations, mcp_function_to_tool_map, mcp_function_input_schema_map, mcp_tool_processes, max_function_declarations_limit, disable_all_mcp_tools

    # Terminate any existing tool processes before reloading config
    for tool_name, process in mcp_tool_processes.items():
        if process.poll() is None:  # Check if the process is running
            try:
                log(f"Terminating old process for tool '{tool_name}'...")
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"Process for '{tool_name}' did not terminate in time, killing.")
                process.kill()
            except Exception as e:
                print(f"Error terminating process for tool '{tool_name}': {e}")
    mcp_tool_processes.clear()

    mcp_function_declarations = []
    mcp_function_to_tool_map = {}
    mcp_function_input_schema_map = {}

    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, 'r') as f:
                mcp_config = json.load(f)
            log(f"MCP config loaded from {MCP_CONFIG_FILE}.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading MCP config: {e}")
            mcp_config = {}
            max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
            return
    else:
        mcp_config = {}
        max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT
        disable_all_mcp_tools = DISABLE_ALL_MCP_TOOLS_DEFAULT
        log("No MCP config file found, MCP tools disabled.")
        return

    max_function_declarations_limit = mcp_config.get("maxFunctionDeclarations", MAX_FUNCTION_DECLARATIONS_DEFAULT)
    if not isinstance(max_function_declarations_limit, int) or max_function_declarations_limit <= 0:
        log(f"Invalid maxFunctionDeclarations in config ({max_function_declarations_limit}). Using default: {MAX_FUNCTION_DECLARATIONS_DEFAULT}")
        max_function_declarations_limit = MAX_FUNCTION_DECLARATIONS_DEFAULT

    disable_all_mcp_tools = mcp_config.get("disableAllTools", DISABLE_ALL_MCP_TOOLS_DEFAULT)
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled by configuration.")

    if mcp_config.get("mcpServers"):
        # Sort servers by priority (higher first), default 0
        sorted_servers = sorted(
            mcp_config["mcpServers"].items(),
            key=lambda item: item[1].get('priority', 0),
            reverse=True
        )

        for tool_name, tool_info in sorted_servers:
            # Skip disabled tools (defaults to enabled if 'enabled' key is missing)
            if not tool_info.get('enabled', True):
                log(f"Skipping disabled tool: '{tool_name}'.")
                continue

            declarations = get_declarations_from_tool(tool_name, tool_info)
            mcp_function_declarations.extend(declarations)
            for decl in declarations:
                if 'name' in decl:
                    mcp_function_to_tool_map[decl['name']] = tool_name
        log(f"Total function declarations loaded: {len(mcp_function_declarations)}")

def create_tool_declarations(prompt_text: str = ""):
    """
    Returns tool declarations for the Gemini API, intelligently selecting them based on the prompt.
    If a tool's name (e.g., 'youtrack') or a function's name (e.g., 'get_issue') is mentioned in the prompt,
    only the functions from the relevant tool(s) are sent. Otherwise, it sends all available functions
    up to the API limit.
    """
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None

    if not mcp_function_declarations:
        return None

    selected_tool_names = set()
    padded_prompt = f' {prompt_text.lower()} '

    # Context-aware tool selection
    if prompt_text:
        # 1. Check for tool server names (e.g., 'youtrack')
        if mcp_config.get("mcpServers"):
            for tool_name in mcp_config["mcpServers"].keys():
                if f' {tool_name.lower()} ' in padded_prompt:
                    log(f"Detected keyword for tool server '{tool_name}'.")
                    selected_tool_names.add(tool_name)

        # 2. Check for individual function names (e.g., 'get_issue')
        for func_decl in mcp_function_declarations:
            func_name = func_decl['name']
            if f' {func_name.lower()} ' in padded_prompt:
                parent_tool_name = mcp_function_to_tool_map.get(func_name)
                if parent_tool_name and parent_tool_name not in selected_tool_names:
                    log(f"Detected keyword for function '{func_name}'. Selecting parent tool '{parent_tool_name}'.")
                    selected_tool_names.add(parent_tool_name)

    # If specific tools were selected, build the declaration list from them
    if selected_tool_names:
        log(f"Final selected tools: {list(selected_tool_names)}")
        selected_declarations = []
        for func_decl in mcp_function_declarations:
            if mcp_function_to_tool_map.get(func_decl['name']) in selected_tool_names:
                selected_declarations.append(func_decl)
        final_declarations = selected_declarations
    else:
        # Fallback: use all declarations
        final_declarations = mcp_function_declarations

    if len(final_declarations) > max_function_declarations_limit:
        log(f"Warning: Number of function declarations ({len(final_declarations)}) exceeds the limit of {max_function_declarations_limit}. Truncating list.")
        final_declarations = final_declarations[:max_function_declarations_limit]

    if not final_declarations:
        return None

    return [{"functionDeclarations": final_declarations}]

def create_tool_declarations_from_list(function_names: list[str]):
    """
    Returns tool declarations for the Gemini API, selecting only those from the specified list of function names.
    This bypasses context-aware selection and respects the max_function_declarations_limit.
    """
    if disable_all_mcp_tools:
        log("All MCP tools are globally disabled. Returning no declarations.")
        return None

    if not mcp_function_declarations or not function_names:
        return None

    selected_declarations = []
    # Handle sentinel for "all functions"
    if function_names == ["*"]:
        log("Selecting all available MCP functions due to '*' sentinel.")
        selected_declarations = mcp_function_declarations[:]  # Make a copy
    else:
        for func_decl in mcp_function_declarations:
            if func_decl.get('name') in function_names:
                selected_declarations.append(func_decl)

    if len(selected_declarations) > max_function_declarations_limit:
        log(f"Warning: Number of function declarations ({len(selected_declarations)}) exceeds the limit of {max_function_declarations_limit}. Truncating list.")
        selected_declarations = selected_declarations[:max_function_declarations_limit]

    if not selected_declarations:
        return None

    return [{"functionDeclarations": selected_declarations}]


def _parse_kwargs_string(s: str) -> dict:
    """
    Parses a simple key=value string (supports quoted values) into a dict.
    Example: 'issue_id="ACS-611" limit=10' -> {'issue_id': 'ACS-611', 'limit': '10'}
    """
    result = {}
    try:
        tokens = shlex.split(s)
        for tok in tokens:
            if '=' in tok:
                k, v = tok.split('=', 1)
                result[k.strip()] = v.strip()
    except Exception as e:
        print(f"Warning: failed to parse kwargs string '{s}': {e}")
    return result

def _normalize_mcp_args(args) -> dict:
    """
    Normalizes functionCall args from Gemini into a JSON object suitable for MCP tools/call.
    Handles:
      - dict with 'kwargs' field containing string or dict
      - plain string (JSON or key=value pairs)
      - already-correct dict
    """
    if args is None:
        return {}
    # If already a dict without wrapper keys
    if isinstance(args, dict) and "kwargs" not in args and "args" not in args:
        return args
    # If dict with kwargs wrapper
    if isinstance(args, dict):
        kwargs_val = args.get("kwargs")
        if isinstance(kwargs_val, dict):
            return kwargs_val
        if isinstance(kwargs_val, str):
            # Try JSON first
            try:
                parsed = json.loads(kwargs_val)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            # Fallback to key=value parsing
            parsed_kv = _parse_kwargs_string(kwargs_val)
            if parsed_kv:
                return parsed_kv
        # If 'args' is a JSON string with object, try it
        args_val = args.get("args")
        if isinstance(args_val, str):
            try:
                parsed_args = json.loads(args_val)
                if isinstance(parsed_args, dict):
                    return parsed_args
            except json.JSONDecodeError:
                pass
        return {}
    # If a raw string
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return _parse_kwargs_string(args)
    # Unknown type
    return {}

def _ensure_dict(value):
    """
    Ensures the value is a dict. If a string, try JSON then key=value parsing.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return _parse_kwargs_string(value)
    return {}

def _coerce_args_to_schema(normalized_args: dict, input_schema: dict) -> dict:
    """
    Coerces normalized arguments into the structure required by input_schema.
    If schema expects 'args'/'kwargs', wrap values accordingly.
    """
    if not isinstance(input_schema, dict):
        return normalized_args

    props = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])

    expects_wrapped = ("args" in props) or ("kwargs" in props) or ("args" in required) or ("kwargs" in required)

    if not expects_wrapped:
        # Pass through normalized args as the flat parameter object
        return normalized_args

    # Build wrapped structure
    result = {}

    # Handle kwargs
    if "kwargs" in props or "kwargs" in required:
        if "kwargs" in normalized_args:
            result["kwargs"] = _ensure_dict(normalized_args.get("kwargs"))
        else:
            # Use entire flat normalized_args as kwargs if non-empty
            result["kwargs"] = normalized_args if isinstance(normalized_args, dict) else {}

    # Handle args
    if "args" in props or "args" in required:
        raw_args = normalized_args.get("args") if isinstance(normalized_args, dict) else None
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                result["args"] = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                result["args"] = []
        elif isinstance(raw_args, list):
            result["args"] = raw_args
        else:
            result["args"] = []

    return result

def execute_mcp_tool(function_name, tool_args):
    """
    Executes an MCP tool function using MCP protocol and returns its output.
    This function maintains a pool of long-running tool processes and reuses them for subsequent calls.
    If a process for a tool is not running, it will be started and initialized.
    """
    global mcp_tool_processes, mcp_request_id_counter

    log(f"Executing MCP function: {function_name} with args: {tool_args}")

    tool_name = mcp_function_to_tool_map.get(function_name)
    if not tool_name:
        return f"Error: Function '{function_name}' not found in any configured MCP tool."

    tool_info = mcp_config.get("mcpServers", {}).get(tool_name)
    if not tool_info:
        return f"Error: Tool '{tool_name}' for function '{function_name}' not found in mcpServers config."

    process = mcp_tool_processes.get(tool_name)

    # If process doesn't exist or has terminated, start a new one
    if process is None or process.poll() is not None:
        if process is not None:
            log(f"Process for tool '{tool_name}' has terminated. Restarting.")
        else:
            log(f"No active process for tool '{tool_name}'. Starting a new one.")

        command = [tool_info["command"]] + tool_info.get("args", [])
        env = os.environ.copy()
        if "env" in tool_info:
            env.update(tool_info["env"])

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            mcp_tool_processes[tool_name] = process

            # Perform MCP handshake
            mcp_init_request = {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gemini-proxy", "version": "1.0.0"}}
            }
            process.stdin.write(json.dumps(mcp_init_request) + "\n")
            process.stdin.flush()
            time.sleep(0.1)

            initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            process.stdin.write(json.dumps(initialized_notification) + "\n")
            process.stdin.flush()
            time.sleep(0.1)
            log(f"Successfully started and initialized process for tool '{tool_name}'.")

        except Exception as e:
            error_message = f"Failed to start or initialize tool '{tool_name}': {e}"
            print(error_message)
            if tool_name in mcp_tool_processes:
                del mcp_tool_processes[tool_name]
            return error_message

    # At this point, `process` should be a valid, running Popen object
    try:
        call_id = mcp_request_id_counter
        mcp_request_id_counter += 1

        normalized_args = _normalize_mcp_args(tool_args)
        input_schema = mcp_function_input_schema_map.get(function_name) or {}
        arguments_for_call = _coerce_args_to_schema(normalized_args, input_schema)

        mcp_call_request = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {
                "name": function_name,
                "arguments": arguments_for_call
            }
        }

        process.stdin.write(json.dumps(mcp_call_request) + "\n")
        process.stdin.flush()

        # Read stdout until we get a response with the matching ID or timeout
        deadline = time.time() + 120
        while time.time() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                if process.poll() is not None:
                    print(f"Tool '{tool_name}' process terminated while waiting for response.")
                    if tool_name in mcp_tool_processes:
                        del mcp_tool_processes[tool_name]
                    return f"Error: Tool '{tool_name}' terminated unexpectedly."
                continue

            line = process.stdout.readline()
            if not line: # EOF
                print(f"Tool '{tool_name}' process closed stdout. Assuming termination.")
                if tool_name in mcp_tool_processes:
                    del mcp_tool_processes[tool_name]
                break

            line = line.strip()
            if not line:
                continue

            try:
                if line.startswith('\ufeff'):
                    line = line.lstrip('\ufeff')
                response = json.loads(line)

                if response.get("id") == call_id:
                    if "result" in response:
                        content = response["result"].get("content", [])
                        # If the content is purely text, concatenate it and return a single string.
                        is_all_text = content and all(item.get("type") == "text" for item in content)
                        if is_all_text:
                            result_text = "".join(item.get("text", "") for item in content)
                            return result_text

                        # For all other cases (mixed content, structured data), return the entire result object as a JSON string.
                        return json.dumps(response["result"])
                    elif "error" in response:
                        return f"MCP Error: {response['error'].get('message', 'Unknown error')}"
                    return "Tool returned a response with no result or error."

            except json.JSONDecodeError:
                print(f"Warning: Could not decode JSON from tool '{tool_name}': {line}")
                continue

        # Timeout occurred
        return f"Error: Function '{function_name}' timed out after 120 seconds."

    except Exception as e:
        error_message = f"An unexpected error occurred while executing function '{function_name}': {e}"
        print(error_message)
        # If a major error occurs, it's safer to terminate the process
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
        if tool_name in mcp_tool_processes:
            del mcp_tool_processes[tool_name]
        return error_message
