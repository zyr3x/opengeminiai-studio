"""
MCP Tool Handling logic for Gemini-Proxy.
"""
import os
import tempfile
import json
import subprocess
import shlex
import select
import threading
import time
import fnmatch
import ast

from .utils import log
from contextlib import contextmanager

# --- BUILT-IN CODE NAVIGATION TOOL DEFINITIONS ---
BUILTIN_TOOL_NAME = "__builtin_code_navigator"

# Thread-local storage to hold the project root for the current request context
_request_context = threading.local()

def get_project_root() -> str:
    """Gets the project root for the current request. Defaults to CWD if not set."""
    return getattr(_request_context, 'project_root', os.path.realpath(os.getcwd()))

@contextmanager
def set_project_root(path: str | None):
    """A context manager to set the project root for the duration of a request."""
    original_path = getattr(_request_context, 'project_root', None)
    if path and os.path.isdir(os.path.expanduser(path)):
        _request_context.project_root = os.path.realpath(os.path.expanduser(path))
    else:
        _request_context.project_root = os.path.realpath(os.getcwd())
    try:
        yield
    finally:
        _request_context.project_root = original_path


CODE_IGNORE_PATTERNS = [
    '.git', '__pycache__', 'node_modules', 'venv', '.venv',
    'build', 'dist', 'target', 'out', 'coverage', '.nyc_output', '*.egg-info', 'bin', 'obj', 'pkg',
    '.idea', '.vscode', '.cache', '.pytest_cache',
    '.DS_Store', 'Thumbs.db',
    '*.log', '*.swp', '*.pyc', '*~', '*.bak', '*.tmp',
    '*.zip', '*.tar.gz', '*.rar', '*.7z',
    '*.o', '*.so', '*.dll', '*.exe', '*.a', '*.lib', '*.dylib',
    '*.class', '*.jar', '*.war',
    '*.pdb', '*.nupkg', '*.deps.json', '*.runtimeconfig.json',
    '*.db', '*.sqlite', '*.sqlite3', 'data.mdb', 'lock.mdb',
    '*.png', '*.jpg', '*.jpeg', '*.gif', '*.svg',
    '*.woff', '*.woff2', '*.ttf', '*.otf', '*.eot', '*.ico',
    '*.mp3', '*.wav', '*.mp4', '*.mov',
    '*.min.js', '*.min.css', '*.map',
    'package-lock-v1.json', 'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock',
]

def _safe_path_resolve(path: str) -> str | None:
    """Resolves a path relative to the current request's project root and checks if it stays within bounds."""
    project_root = get_project_root()
    # We always join the relative path to the project_root first
    full_path = os.path.join(project_root, path)
    resolved_path = os.path.realpath(full_path)

    # Crucial safety check: ensure the resolved path remains within the project root
    if not resolved_path.startswith(project_root):
        log(f"Security violation attempt: Path '{path}' resolves outside project root ({resolved_path} vs {project_root}).")
        return None
    return resolved_path

def _generate_tree_local(file_paths, root_name):
    """Generates an ASCII directory tree from a list of relative file paths."""
    tree_dict = {}
    for path_str in file_paths:
        # Use '/' as separator internally regardless of OS for consistent path parts splitting
        path_str = path_str.replace(os.sep, '/')
        parts = path_str.split('/')
        current_level = tree_dict
        for part in parts:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]

    def build_tree_lines(d, prefix=''):
        lines = []
        entries = sorted(d.keys())
        for i, entry in enumerate(entries):
            connector = '├── ' if i < len(entries) - 1 else '└── '
            lines.append(f"{prefix}{connector}{entry}")
            if d[entry]:
                extension = '│   ' if i < len(entries) - 1 else '    '
                lines.extend(build_tree_lines(d[entry], prefix + extension))
        return lines

    tree_lines = [root_name]
    tree_lines.extend(build_tree_lines(tree_dict))
    return "\n".join(tree_lines)


def list_files(path: str = ".", max_depth: int = -1) -> str:
    """
    Lists files and directories recursively for code context.
    Respects common ignore patterns. Returns an ASCII tree structure.
    An optional max_depth can be specified to limit traversal depth (e.g., max_depth=3).
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: Path '{path}' not found or inaccessible."

    if os.path.isfile(resolved_path):
        return f"Path '{path}' is a file, not a directory. Use get_file_content."

    relative_paths = []
    MAX_FILES_LISTED = 500
    file_count = 0
    start_level = resolved_path.count(os.sep)

    try:
        for root, dirs, files in os.walk(resolved_path, topdown=True):
            current_level = root.count(os.sep)
            depth = current_level - start_level

            rel_root_abs = os.path.relpath(root, resolved_path)
            rel_root = '' if rel_root_abs == '.' else rel_root_abs

            # Filter directories in place first
            dirs[:] = [d for d in dirs if not (
                    d.startswith('.') or
                    any(fnmatch.fnmatch(os.path.join(rel_root, d).replace(os.sep, '/'), p) or fnmatch.fnmatch(d, p) for p in CODE_IGNORE_PATTERNS)
            )]

            # If max_depth is set, stop descending further once reached
            if max_depth != -1 and depth >= max_depth:
                dirs[:] = []

            for filename in files:
                if file_count >= MAX_FILES_LISTED:
                    dirs[:] = []  # Stop traversing deeper
                    break

                rel_filepath_fs = os.path.join(rel_root, filename)
                rel_filepath_norm = rel_filepath_fs.replace(os.sep, '/')

                if filename.startswith('.'): continue

                if any(fnmatch.fnmatch(rel_filepath_norm, p) or fnmatch.fnmatch(filename, p) for p in CODE_IGNORE_PATTERNS):
                    continue

                relative_paths.append(rel_filepath_fs)
                file_count += 1

            if file_count >= MAX_FILES_LISTED:
                log(f"Warning: List files stopped at {MAX_FILES_LISTED} files to prevent large context.")
                break
    except Exception as e:
        log(f"Error during file listing for path '{path}': {e}")
        return f"Error: Failed to list directory contents due to system error."


    # Determine the name to display as the root of the tree
    tree_root_name = path if path != "." else os.path.basename(get_project_root())

    if not relative_paths:
        return f"Directory '{path}' is empty or contains only ignored files."

    return "Project structure:\n" + _generate_tree_local(relative_paths, tree_root_name)

def get_file_content(path: str) -> str:
    """
    Reads the content of a single file, respecting safety bounds and size limits.
    Returns the file content formatted as a code snippet.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."

    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."

    MAX_FILE_SIZE_BYTES = 256 * 1024 # 256 KB

    try:
        file_size = os.path.getsize(resolved_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"Error: File size ({file_size / 1024:.2f} KB) exceeds the maximum allowed limit of 256 KB."

        # Basic binary check (quick heuristic)
        with open(resolved_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return f"Error: File '{path}' appears to be a binary file. Cannot read."

        # Read content (assuming UTF-8, ignore errors)
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            code_content = f.read()

        _, extension = os.path.splitext(resolved_path)
        lang = extension.lstrip('.') if extension else ''

        return (
            f"\n--- Code File: {path} ({file_size / 1024:.2f} KB) ---\n"
            f"```{lang}\n{code_content}\n```\n"
        )

    except Exception as e:
        return f"Error reading file '{path}': {e}"

def list_symbols_in_file(path: str) -> str:
    """
    Parses a Python file to list top-level functions and classes.
    This is useful for quickly understanding the structure of a file.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."

    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tree = ast.parse(content)
        symbols = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                symbols.append(f"  - [Function] {node.name}")
            elif isinstance(node, ast.ClassDef):
                symbols.append(f"  - [Class]    {node.name}")
        if not symbols:
            return f"File '{path}' does not contain any top-level functions or classes."
        return f"Symbols in {path}:\n" + "\n".join(symbols)
    except Exception as e:
        return f"Error parsing file '{path}': {e}"

def get_code_snippet(path: str, symbol_name: str) -> str:
    """
    Extracts the source code of a specific function or class from a Python file.
    Use this after finding a symbol with `list_symbols_in_file`.
    """
    resolved_path = _safe_path_resolve(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return f"Error: File '{path}' not found or inaccessible."
    if not os.path.isfile(resolved_path):
        return f"Error: Path '{path}' is a directory, not a file."

    try:
        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == symbol_name:
                # ast.get_source_segment is the most reliable way to get the exact source
                snippet = ast.get_source_segment(content, node)
                if snippet:
                    lang = "python"
                    return (
                        f"\n--- Code Snippet: {symbol_name} from {path} ---\n"
                        f"```{lang}\n{snippet}\n```\n"
                    )
        return f"Error: Symbol '{symbol_name}' not found in file '{path}'."
    except Exception as e:
        return f"Error processing file '{path}' for symbol '{symbol_name}': {e}"

def search_codebase(query: str) -> str:
    """
    Searches the entire project codebase for a specific query string.
    Uses 'ripgrep' (rg) if available for speed and .gitignore support, otherwise falls back to 'grep'.
    Returns a formatted list of matches, including file paths and line numbers.
    """
    MAX_SEARCH_RESULTS = 100
    try:
        # Check if ripgrep (rg) is installed. We prefer it for its speed and gitignore handling.
        subprocess.run(['rg', '--version'], check=True, capture_output=True)
        # Use ripgrep with vimgrep format (file:line:col:text), which is structured and easy for an LLM to parse.
        command = ['rg', '--vimgrep', '--max-count', str(MAX_SEARCH_RESULTS), '--', query, '.']
        log(f"Using ripgrep for search with command: {' '.join(command)}")
        result = subprocess.run(
            command, cwd=get_project_root(), capture_output=True, text=True, check=False
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback to grep if ripgrep is not available.
        log("ripgrep not found, falling back to grep. For better performance, install ripgrep.")
        exclude_dirs = [f'--exclude-dir={pattern}' for pattern in [
            '.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist', 'target', '.idea', '.vscode'
        ]]
        command = ['grep', '-r', '-n', '-I'] + exclude_dirs + ['-e', query, '.']
        log(f"Using grep for search with command: {' '.join(command)}")
        result = subprocess.run(
            command, cwd=get_project_root(), capture_output=True, text=True, check=False
        )

    if result.returncode not in [0, 1]:  # 0 = success with matches, 1 = success with no matches
        return f"Error executing search command. Return code: {result.returncode}\nStderr: {result.stderr}"

    output = result.stdout.strip()
    if not output:
        return f"No results found for query: '{query}'"

    lines = output.split('\n')
    if len(lines) > MAX_SEARCH_RESULTS:
        output = "\n".join(lines[:MAX_SEARCH_RESULTS])
        output += f"\n... (truncated to {MAX_SEARCH_RESULTS} results)"

    return f"Search results for '{query}':\n```\n{output}\n```"

def apply_patch(patch_content: str) -> str:
    """
    Applies a patch to the codebase to modify files.
    The user must provide the patch content in the standard unified diff format (e.g., from `git diff`).
    This tool should be used as the final step when a user asks to fix, refactor, or add code.
    """
    if not patch_content or not isinstance(patch_content, str):
        return "Error: Patch content must be a non-empty string."

    # Clean up potential markdown formatting from the LLM's output
    if patch_content.strip().startswith("```"):
        patch_content = "\n".join(patch_content.strip().split('\n')[1:-1])

    """
    Applies a git-style patch string to the project codebase using the system's `patch` utility.

    This function securely writes the patch content to a temporary file and executes the
    `patch -p1` command from the project root.

    Args:
        patch_content: A string containing the patch in the standard unified diff format.

    Returns:
        A string indicating the success or failure of the patch application, including
        error messages if applicable.
    """
    log(f"Attempting to apply patch:\n---\n{patch_content}\n---")

    try:
        # Use a secure temporary file to pass the patch to the command
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write(patch_content)
            temp_patch_file = tmp.name

        try:
            # The `patch` command is standard on Linux/macOS. -p1 strips the 'a/' and 'b/' prefixes.
            command = ['patch', '-p1', f'--input={temp_patch_file}']
            result = subprocess.run(
                command, cwd=get_project_root(), capture_output=True, text=True, check=False
            )
        finally:
            if os.path.exists(temp_patch_file):
                os.remove(temp_patch_file)

        if result.returncode == 0:
            success_message = "Patch applied successfully."
            if result.stdout:
                success_message += f"\nOutput:\n{result.stdout}"
            log(success_message)
            return success_message
        else:
            error_message = f"Error applying patch. Return code: {result.returncode}"
            if result.stderr:
                error_message += f"\nStderr:\n{result.stderr}"
            if result.stdout:
                error_message += f"\nStdout:\n{result.stdout}"
            log(error_message)
            return error_message

    except Exception as e:
        if os.path.exists("temp_patch.diff"):
            os.remove("temp_patch.diff")
        log(f"Failed to execute patch command: {e}")
        return f"Error: An unexpected exception occurred while trying to apply the patch: {e}"

BUILTIN_FUNCTIONS = {
    "list_files": list_files,
    "get_file_content": get_file_content,
    "list_symbols_in_file": list_symbols_in_file,
    "get_code_snippet": get_code_snippet,
    "search_codebase": search_codebase,
    "apply_patch": apply_patch
}

BUILTIN_DECLARATIONS = [
    {
        "name": "list_files",
        "description": "Lists files and directories recursively from a starting path, returning an ASCII directory tree structure. This is the first step to understand the project layout before fetching file content. Use '.' to list the current project root. Results are filtered by standard ignore rules (e.g., .git, venv, build artifacts).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The starting path relative to the current working directory. Use '.' for the project root."
                },
                "max_depth": {
                    "type": "INTEGER",
                    "description": "Optional. The maximum depth of directories to traverse. `max_depth=1` lists the current directory."
                }
            }
        }
    },
    {
        "name": "get_file_content",
        "description": "Reads and returns the content of a single specified text file. Use this after identifying the file via list_files. Limited to 256 KB per file.",
        "parameters": {
            "type": "OBJECT",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The path to the file relative to the current working directory."
                }
            }
        }
    },
    {
        "name": "search_codebase",
        "description": "Performs a fast, line-based search for a string query across all files in the project, returning matching lines with their file paths and line numbers. Ideal for finding where functions are called or variables are defined.",
        "parameters": {
            "type": "OBJECT",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The string or regular expression to search for."
                }
            }
        }
    },
    {
        "name": "apply_patch",
        "description": "Applies a code patch (in unified diff format) to the codebase. Use this for making code changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch_content": {
                    "type": "string",
                    "description": "The patch content in unified diff format (e.g., as generated by 'git diff')."
                }
            },
            "required": ["patch_content"]
        }
    }
]
# --- END BUILT-IN CODE NAVIGATION TOOL DEFINITIONS ---


# --- MCP Tool Configuration ---
mcp_config = {}
mcp_config = {}
MCP_CONFIG_FILE = 'var/config/mcp.json'
mcp_function_declarations = []  # A flat list of all function declarations from all tools
mcp_function_to_tool_map = {}   # Maps a function name to its parent tool name (from mcpServers)
mcp_function_input_schema_map = {}  # Maps a function name to its inputSchema from MCP
mcp_tool_processes = {}  # Cache for running tool subprocesses
mcp_request_id_counter = 1  # Counter for unique JSON-RPC request IDs
mcp_request_id_lock = threading.Lock() # Lock to ensure thread-safe request ID generation

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
                "clientInfo": {"name": "gemini-proxy", "version": "2.1.0"}
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

    # 1. Load Declarations from External MCP Servers
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

    # 2. Add Built-in Code Navigation Tool (always registered)
    mcp_function_declarations.extend(BUILTIN_DECLARATIONS)
    for decl in BUILTIN_DECLARATIONS:
        if 'name' in decl:
            mcp_function_to_tool_map[decl['name']] = BUILTIN_TOOL_NAME
            # Built-in tools have no external schema, use empty dict for input coercion logic safety
            mcp_function_input_schema_map[decl['name']] = {}

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

    # Handle built-in tools (executed locally)
    if tool_name == BUILTIN_TOOL_NAME:
        builtin_func = BUILTIN_FUNCTIONS.get(function_name)
        if not builtin_func:
            return f"Error: Built-in function '{function_name}' not implemented."

        normalized_args = _normalize_mcp_args(tool_args)

        # Prepare args for the specific built-in function call
        func_args = {}
        try:
            if function_name == 'list_files':
                path = normalized_args.get('path')
                func_args['path'] = path if path is not None else '.'

                if 'max_depth' in normalized_args:
                    max_depth_val = normalized_args.get('max_depth')
                    if max_depth_val is not None:
                        func_args['max_depth'] = int(max_depth_val)

            elif function_name == 'get_file_content':
                path = normalized_args['path']
                if path is None:
                    raise TypeError("Path argument cannot be null.")
                func_args['path'] = path

            elif function_name == 'list_symbols_in_file':
                path = normalized_args['path']
                if path is None:
                    raise TypeError("Path argument cannot be null.")
                func_args['path'] = path

            elif function_name == 'get_code_snippet':
                path = normalized_args['path']
                symbol_name = normalized_args['symbol_name']
                if path is None:
                    raise TypeError("Path argument cannot be null.")
                if symbol_name is None:
                    raise TypeError("Symbol name argument cannot be null.")
                func_args['path'] = path
                func_args['symbol_name'] = symbol_name

            elif function_name == 'search_codebase':
                query = normalized_args['query']
                if query is None:
                    raise TypeError("Query argument cannot be null.")
                func_args['query'] = query

            elif function_name == 'apply_patch':
                patch_content = normalized_args['patch_content']
                if patch_content is None:
                    raise TypeError("Patch content argument cannot be null.")
                result = apply_patch(patch_content=patch_content)
                return result
        except KeyError as e:
            log(f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'. Normalized args: {normalized_args}")
            return f"Error: Missing required argument '{e.args[0]}' for function '{function_name}'."
        except (ValueError, TypeError) as e:
            log(f"Error: Invalid argument type or null value provided for function '{function_name}'. Details: {e}. Normalized args: {normalized_args}")
            return f"Error: Invalid argument type provided for function '{function_name}': {e}"

        try:
            result = builtin_func(**func_args)
            return result
        except Exception as e:
            log(f"Error executing built-in tool {function_name} with args {func_args}: {type(e).__name__}: {e}")
            return f"Error executing built-in function '{function_name}': {e}"


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
        with mcp_request_id_lock:
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

        # Read stdout/stderr until we get a response with the matching ID or timeout
        deadline = time.time() + 120
        while time.time() < deadline:
            # Watch both stdout and stderr to prevent stderr buffer from filling up and causing a deadlock
            ready_to_read, _, _ = select.select([process.stdout, process.stderr], [], [], 0.5)

            if not ready_to_read:
                # If select times out, check if the process has terminated
                if process.poll() is not None:
                    print(f"Tool '{tool_name}' process terminated while waiting for response.")
                    stderr_output = process.stderr.read()
                    if stderr_output:
                        print(f"Stderr from '{tool_name}': {stderr_output.strip()}")
                    if tool_name in mcp_tool_processes:
                        del mcp_tool_processes[tool_name]
                    return f"Error: Tool '{tool_name}' terminated unexpectedly."
                continue  # Continue waiting for I/O

            # Drain stderr to prevent blocking
            if process.stderr in ready_to_read:
                err_line = process.stderr.readline()
                if err_line:
                    print(f"Warning (stderr from '{tool_name}'): {err_line.strip()}")

            # Process stdout for the response
            if process.stdout in ready_to_read:
                line = process.stdout.readline()
                if not line:  # EOF
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
