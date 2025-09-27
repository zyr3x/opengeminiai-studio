"""
 BelVG LLC.

 NOTICE OF LICENSE

 This source file is subject to the EULA
 that is bundled with this package in the file LICENSE.txt.
 It is also available through the world-wide-web at this URL:
 https://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

 *******************************************************************
 @category   BelVG
 @author     Oleg Semenov
 @copyright  Copyright (c) BelVG LLC. (http://www.belvg.com)
 @license    http://store.belvg.com/BelVG-LICENSE-COMMUNITY.txt

"""
import os
import requests
from flask import Flask, request, jsonify, Response, redirect, url_for
import time
import json
from requests.exceptions import HTTPError, ConnectionError, Timeout, RequestException
import base64
import re
from dotenv import load_dotenv, set_key
import subprocess
import shlex
import select

app = Flask(__name__)

# Load environment variables from .env file at startup
load_dotenv()

# --- MCP Tool Configuration ---
mcp_config = {}
MCP_CONFIG_FILE = 'mcp_config.json'
mcp_function_declarations = []  # A flat list of all function declarations from all tools
mcp_function_to_tool_map = {}   # Maps a function name to its parent tool name (from mcpServers)
mcp_function_input_schema_map = {}  # Maps a function name to its inputSchema from MCP

def get_declarations_from_tool(tool_name, tool_info):
    """Fetches function declaration schema(s) from an MCP tool using MCP protocol."""
    global mcp_function_input_schema_map
    command = [tool_info["command"]] + tool_info.get("args", [])
    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        print(f"Fetching schema for tool '{tool_name}'...")

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

        print(f"Successfully fetched {len(tools)} function declaration(s) for tool '{tool_name}'.")
        return tools

    except subprocess.TimeoutExpired:
        print(f"Error: Timeout while fetching schema for tool '{tool_name}'.")
    except Exception as e:
        print(f"An unexpected error occurred while fetching schema for tool '{tool_name}': {e}")

    return []

def load_mcp_config():
    """Loads MCP tool configuration from file and fetches schemas for all configured tools."""
    global mcp_config, mcp_function_declarations, mcp_function_to_tool_map, mcp_function_input_schema_map
    mcp_function_declarations = []
    mcp_function_to_tool_map = {}
    mcp_function_input_schema_map = {}

    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, 'r') as f:
                mcp_config = json.load(f)
            print(f"MCP config loaded from {MCP_CONFIG_FILE}.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading MCP config: {e}")
            mcp_config = {}
            return
    else:
        mcp_config = {}
        print("No MCP config file found, MCP tools disabled.")
        return

    if mcp_config.get("mcpServers"):
        for tool_name, tool_info in mcp_config["mcpServers"].items():
            declarations = get_declarations_from_tool(tool_name, tool_info)
            mcp_function_declarations.extend(declarations)
            for decl in declarations:
                if 'name' in decl:
                    mcp_function_to_tool_map[decl['name']] = tool_name
        print(f"Total function declarations loaded: {len(mcp_function_declarations)}")


load_mcp_config()
# --- End MCP Config ---

# --- Prompt Engineering Config ---
PROMPT_OVERRIDES_FILE = 'prompt_config.json'
prompt_overrides = {}

def load_prompt_config():
    """Loads prompt overrides from JSON file into the global prompt_overrides dict."""
    global prompt_overrides
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, 'r') as f:
                prompt_overrides = json.load(f)
            print(f"Prompt overrides loaded from {PROMPT_OVERRIDES_FILE}.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading prompt overrides: {e}")
            prompt_overrides = {}
    else:
        prompt_overrides = {}

# Load prompt overrides at startup
load_prompt_config()

API_KEY = os.getenv("API_KEY")

UPSTREAM_URL = os.getenv("UPSTREAM_URL")
if not UPSTREAM_URL:
    raise ValueError("UPSTREAM_URL environment variable not set")


cached_models_response = None
model_info_cache = {}
TOKEN_ESTIMATE_SAFETY_MARGIN = 0.95  # Use 95% of the model's capacity


# --- Helper Functions for Multimodal Support ---

def _process_image_url(image_url: dict) -> dict | None:
    """
    Processes an OpenAI image_url object and converts it to a Gemini inline_data part.
    Supports both web URLs and Base64 data URIs.
    """
    url = image_url.get("url")
    if not url:
        return None

    try:
        if url.startswith("data:"):
            # Handle Base64 data URI
            match = re.match(r"data:(image/.+);base64,(.+)", url)
            if not match:
                print(f"Warning: Could not parse data URI.")
                return None
            mime_type, base64_data = match.groups()
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
        else:
            # Handle web URL
            print(f"Downloading image from URL: {url}")
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            mime_type = response.headers.get("Content-Type", "image/jpeg")
            base64_data = base64.b64encode(response.content).decode('utf-8')
            return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
    except Exception as e:
        print(f"Error processing image URL {url}: {e}")
        return None


# --- Helper Functions for Token Management ---

def get_model_input_limit(model_name: str) -> int:
    """
    Fetches the input token limit for a given model from the Gemini API and caches it.
    """
    if model_name in model_info_cache:
        return model_info_cache[model_name].get("inputTokenLimit", 8192)  # Default to 8k if not found

    try:
        print(f"Cache miss for {model_name}. Fetching model details from API...")
        GEMINI_MODEL_INFO_URL = f"{UPSTREAM_URL}/v1beta/models/{model_name}"
        params = {"key": API_KEY}
        response = requests.get(GEMINI_MODEL_INFO_URL, params=params)
        response.raise_for_status()
        model_info = response.json()
        model_info_cache[model_name] = model_info
        return model_info.get("inputTokenLimit", 8192)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching model details for {model_name}: {e}. Using default limit of 8192.")
        return 8192  # Return a safe default on error


def estimate_token_count(contents: list) -> int:
    """
    Estimates the token count of the 'contents' list using a character-based heuristic.
    Approximation: 4 characters per token.
    """
    total_chars = 0
    for item in contents:
        for part in item.get("parts", []):
            if "text" in part:
                total_chars += len(part.get("text", ""))
    return total_chars // 4


def truncate_contents(contents: list, limit: int) -> list:
    """
    Truncates the 'contents' list by removing older messages (but keeping the first one)
    until the estimated token count is within the specified limit.
    """
    estimated_tokens = estimate_token_count(contents)
    if estimated_tokens <= limit:
        return contents

    print(f"Estimated token count ({estimated_tokens}) exceeds limit ({limit}). Truncating...")

    # Keep the first message (often a system prompt) and the most recent ones.
    # We will remove messages from the second position (index 1).
    truncated_contents = contents.copy()
    while estimate_token_count(truncated_contents) > limit and len(truncated_contents) > 1:
        # Remove the oldest message after the initial system/user prompt
        truncated_contents.pop(1)

    final_tokens = estimate_token_count(truncated_contents)
    print(f"Truncation complete. Final estimated token count: {final_tokens}")
    return truncated_contents


# --- API Endpoints ---
@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    """
    Sets the API_KEY from a web form and saves it to the .env file for persistence.
    """
    global API_KEY, cached_models_response, model_info_cache
    new_key = request.form.get('api_key')
    if new_key:
        # Update the key in the current session
        API_KEY = new_key

        # Save the key to the .env file for persistence across restarts
        set_key('.env', 'API_KEY', new_key)
        print("API Key has been updated via web interface and saved to .env file.")

        # Clear model cache if key changes
        cached_models_response = None
        model_info_cache = {}
        print("Caches cleared due to API key change.")
    return redirect(url_for('index'))

@app.route('/set_mcp_config', methods=['POST'])
def set_mcp_config():
    """Saves MCP tool configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('mcp_config')
    if config_str:
        try:
            # Validate JSON before writing
            json.loads(config_str.strip())
            with open(MCP_CONFIG_FILE, 'w') as f:
                f.write(config_str.strip())
            print(f"MCP config updated and saved to {MCP_CONFIG_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in MCP config: {e}")
            # Don't reload config if JSON is invalid
            return redirect(url_for('index'))
    elif os.path.exists(MCP_CONFIG_FILE):
        # Handle empty submission: clear the config
        os.remove(MCP_CONFIG_FILE)
        print("MCP config cleared.")

    load_mcp_config()  # Reload config and fetch new schemas
    return redirect(url_for('index'))

@app.route('/set_prompt_config', methods=['POST'])
def set_prompt_config():
    """Saves prompt override configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('prompt_overrides')
    if config_str:
        try:
            # Validate JSON before writing
            json.loads(config_str.strip())
            with open(PROMPT_OVERRIDES_FILE, 'w') as f:
                f.write(config_str.strip())
            print(f"Prompt overrides updated and saved to {PROMPT_OVERRIDES_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in prompt overrides: {e}")
            # Don't reload config if JSON is invalid
            return redirect(url_for('index'))
    elif os.path.exists(PROMPT_OVERRIDES_FILE):
        # Handle empty submission: clear the config
        os.remove(PROMPT_OVERRIDES_FILE)
        print("Prompt overrides config cleared.")

    load_prompt_config()
    return redirect(url_for('index'))



@app.route('/', methods=['GET'])
def index():
    """
    Serves a simple documentation page in English.
    """
    api_key_status = "Set" if API_KEY else "Not Set"

    current_mcp_config_str = ""
    if os.path.exists(MCP_CONFIG_FILE):
        with open(MCP_CONFIG_FILE, 'r') as f:
            current_mcp_config_str = f.read()

    current_prompt_overrides_str = ""
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        with open(PROMPT_OVERRIDES_FILE, 'r') as f:
            current_prompt_overrides_str = f.read()

    default_prompt_overrides = {
      "default_chat": {
        "triggers": ["You are a JetBrains AI Assistant for code development."],
        "overrides": {
          "Follow the user's requirements carefully & to the letter.": ""
        }
      },
      "commit_message": {
        "triggers": ["Follow the style of the author's recent commit messages"],
        "overrides": {
          "Generate a concise commit message in the imperative mood for the following Git diff.": "Write a short and professional commit message for the following changes:"
        }
      }
    }

    default_mcp_config = {
      "mcpServers": {
        "youtrack": {
          "command": "docker",
          "args": [
            "run", "--rm", "-i",
            "-e", "YOUTRACK_API_TOKEN",
            "-e", "YOUTRACK_URL",
            "tonyzorin/youtrack-mcp:latest"
          ],
          "env": {
            "YOUTRACK_API_TOKEN": "perm-your-token-here",
            "YOUTRACK_URL": "https://youtrack.example.com/"
          }
        }
      }
    }

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gemini to OpenAI Proxy</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; padding: 2em; max-width: 800px; margin: auto; color: #333; background-color: #f9f9f9; }}
            h1, h2 {{ color: #1a73e8; }}
            code {{ background-color: #e0e0e0; padding: 2px 6px; border-radius: 4px; font-family: "SF Mono", "Fira Code", "Source Code Pro", monospace; }}
            pre {{ background-color: #e0e0e0; padding: 1em; border-radius: 4px; overflow-x: auto; }}
            .container {{ background-color: #fff; padding: 2em; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            .footer {{ margin-top: 2em; text-align: center; font-size: 0.9em; color: #777; }}
            li {{ margin-bottom: 0.5em; }}
            input[type="text"] {{ padding: 8px; width: 70%; border-radius: 4px; border: 1px solid #ccc; }}
            input[type="submit"] {{ padding: 8px 16px; border-radius: 4px; border: none; background-color: #1a73e8; color: white; cursor: pointer; }}
            textarea {{ padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 95%; font-family: "SF Mono", "Fira Code", "Source Code Pro", monospace; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Gemini to OpenAI Proxy</h1>
            <p>This is a lightweight proxy server that translates requests from an OpenAI-compatible client (like JetBrains AI Assistant) to Google's Gemini API.</p>

            <h2>API Key Setup</h2>
            <p>You can set your Gemini API Key using the form below. The key is stored in memory and will be reset when the server restarts. You can also set it permanently using the <code>API_KEY</code> environment variable.</p>
            <form action="/set_api_key" method="POST">
                <label for="api_key"><b>Gemini API Key:</b></label><br>
                <input type="text" id="api_key" name="api_key" placeholder="Enter your Gemini API key" size="60" value="{API_KEY or ''}">
                <input type="submit" value="Save Key">
            </form>
            <p><b>Current Status:</b> The API Key is currently <strong>{api_key_status}</strong>.</p>

            <h2>MCP Tools Configuration</h2>
            <p>Configure MCP tools by providing a JSON configuration. This will be saved to <code>mcp_config.json</code>.</p>
            <p>You can also use keywords in your prompt to control tool usage: <code>--nocmds</code> to disable them for a single request.</p>
            <form action="/set_mcp_config" method="POST">
                <label for="mcp_config"><b>MCP JSON Config:</b></label><br>
                <textarea id="mcp_config" name="mcp_config" rows="15">{current_mcp_config_str or pretty_json(default_mcp_config)}</textarea><br><br>
                <input type="submit" value="Save MCP Config">
            </form>

            <h2>Prompt Engineering</h2>
            <p>Define different profiles for prompt overrides. Each profile has a name, a list of 'triggers' to activate it, and an 'overrides' dictionary for replacements. The proxy will check incoming messages for trigger phrases and apply the overrides from the first matching profile. This is useful for handling different contexts, like regular chat vs. commit message generation.</p>
            <form action="/set_prompt_config" method="POST">
                <label for="prompt_overrides"><b>Prompt Overrides (JSON):</b></label><br>
                <textarea id="prompt_overrides" name="prompt_overrides" rows="10">{current_prompt_overrides_str or pretty_json(default_prompt_overrides)}</textarea><br><br>
                <input type="submit" value="Save Prompt Overrides">
            </form>
            
            <h2>What It Does</h2>
            <ul>
                <li>Accepts requests on OpenAI-like endpoints: <code>/v1/chat/completions</code> and <code>/v1/models</code>.</li>
                <li>Transforms the request format from OpenAI's structure to Gemini's structure.</li>
                <li>Handles streaming responses for chat completions.</li>
                <li>Manages basic conversation history truncation to fit within the model's token limits.</li>
                <li>Caches model lists to reduce upstream API calls.</li>
                <li>Supports multimodal requests (text and images).</li>
                <li>Supports MCP tools for function calling.</li>
            </ul>

            <h2>How to Use</h2>

            <h3>1. Setup and Run</h3>
            <p>Before running the server, you need to set one environment variable (or use the form above for the API Key):</p>
            <pre><code> export API_KEY="YOUR_GEMINI_API_KEY"
 export UPSTREAM_URL="https://generativelanguage.googleapis.com"</code></pre>
            <p>Then, run the server:</p>
            <pre><code> python3.12 -m venv
 source venv/bin/activate
 pip install -r requirements.txt
 python3.12 gemini-proxy.py</code></pre>
            <p>or Docker Version</p>
            <pre><code>docker-composer up -d</code></pre>
            <p>The server will start on <code>http://0.0.0.0:8080</code> by default.</p>
        
            
            <h3>2. Configure JetBrains AI Assistant</h3>
            <p>To use this proxy with JetBrains IDEs:</p>
            <ol>
                <li>Open AI Assistant settings (<code>Settings</code> > <code>Tools</code> > <code>AI Assistant</code> > <code>Models</code>).</li>
                <li>Select the "OpenAI API" service.</li>
                <li>Set the <b>Server URL</b> to: <code>http://&lt;your-server-ip-or-localhost&gt;:8080/v1/openai</code></li>
                <li>The model list will be fetched automatically. You can leave it as default or choose a specific one.</li>
            </ol>
            <p><b>Note:</b> The path must end with <code>/v1/</code> because the IDE will append <code>/chat/completions</code> or <code>/models</code> to it.</p>

            <h2>Available Endpoints</h2>
            <ul>
                <li><code>GET /</code>: This documentation and setup page.</li>
                <li><code>GET /v1/models</code>: Lists available Gemini models in OpenAI format.</li>
                <li><code>POST /v1/chat/completions</code>: The main endpoint for chat completions. Supports streaming.</li>
            </ul>

            <div class="footer">
                <p>Proxy server is running and ready to serve requests.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content

def create_tool_declarations():
    """Returns the cached tool declarations in the format expected by the Gemini API."""
    if not mcp_function_declarations:
        return None
    return [{"functionDeclarations": mcp_function_declarations}]

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
    """Executes an MCP tool function using MCP protocol and returns its output."""
    print(f"Executing MCP function: {function_name} with args: {tool_args}")

    tool_name = mcp_function_to_tool_map.get(function_name)
    if not tool_name:
        return f"Error: Function '{function_name}' not found in any configured MCP tool."

    tool_info = mcp_config.get("mcpServers", {}).get(tool_name)
    if not tool_info:
        return f"Error: Tool '{tool_name}' for function '{function_name}' not found in mcpServers config."

    command = [tool_info["command"]] + tool_info.get("args", [])

    env = os.environ.copy()
    if "env" in tool_info:
        env.update(tool_info["env"])

    try:
        # Send MCP initialization and tool call request
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

        normalized_args = _normalize_mcp_args(tool_args)
        # Coerce arguments to match the MCP tool's input schema if available
        input_schema = mcp_function_input_schema_map.get(function_name) or {}
        arguments_for_call = _coerce_args_to_schema(normalized_args, input_schema)

        mcp_call_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": function_name,
                "arguments": arguments_for_call
            }
        }

        # Keep stdio session open while waiting for the response to avoid server-side ClosedResourceError
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        result_to_return = None
        try:
            # Write initialize
            process.stdin.write(json.dumps(mcp_init_request) + "\n")
            process.stdin.flush()
            time.sleep(0.05)

            # Write notifications/initialized
            initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            process.stdin.write(json.dumps(initialized_notification) + "\n")
            process.stdin.flush()
            time.sleep(0.05)

            # Write tools/call
            process.stdin.write(json.dumps(mcp_call_request) + "\n")
            process.stdin.flush()

            # Read stdout until we get id == 1 response or timeout
            deadline = time.time() + 120
            buffer = ""
            while time.time() < deadline:
                # Wait until stdout is ready or process exits
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if ready:
                    line = process.stdout.readline()
                    if not line:
                        # EOF
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if line.startswith('\ufeff'):
                            line = line.lstrip('\ufeff')
                        response = json.loads(line)
                        if response.get("id") == 1:
                            if "result" in response:
                                content = response["result"].get("content", [])
                                if content:
                                    # Extract text content from MCP response
                                    result_text = ""
                                    for item in content:
                                        if item.get("type") == "text":
                                            result_text += item.get("text", "")
                                    result_to_return = result_text if result_text else str(response["result"])
                                else:
                                    result_to_return = str(response["result"])
                                break
                            elif "error" in response:
                                result_to_return = f"MCP Error: {response['error'].get('message', 'Unknown error')}"
                                break
                    except json.JSONDecodeError:
                        continue
                # If process exited, stop waiting
                if process.poll() is not None:
                    break

            # If no parsed result yet, try to consume remaining buffered stdout
            if result_to_return is None:
                try:
                    remaining = process.stdout.read() or ""
                except Exception:
                    remaining = ""
                if remaining:
                    # Try to parse last meaningful line
                    for raw in remaining.strip().splitlines()[::-1]:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            if raw.startswith('\ufeff'):
                                raw = raw.lstrip('\ufeff')
                            r = json.loads(raw)
                            if r.get("id") == 1:
                                if "result" in r:
                                    content = r["result"].get("content", [])
                                    if content:
                                        rt = ""
                                        for it in content:
                                            if it.get("type") == "text":
                                                rt += it.get("text", "")
                                        result_to_return = rt if rt else str(r["result"])
                                    else:
                                        result_to_return = str(r["result"])
                                elif "error" in r:
                                    result_to_return = f"MCP Error: {r['error'].get('message', 'Unknown error')}"
                                break
                        except json.JSONDecodeError:
                            continue

        finally:
            # Close stdin after we've read the response to let server exit cleanly
            try:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except Exception:
                pass
            # Give the process a moment to exit
            try:
                process.wait(timeout=2)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass

        # Prefer the parsed result; otherwise, return raw stdout/stderr info
        if result_to_return is not None:
            return result_to_return

        # Fallback: emit captured output if available
        try:
            stdout_tail = process.stdout.read() if process.stdout else ""
            stderr_tail = process.stderr.read() if process.stderr else ""
        except Exception:
            stdout_tail = ""
            stderr_tail = ""
        if stderr_tail:
            print(f"Function '{function_name}' stderr: {stderr_tail}")
        print(f"Function '{function_name}' stdout: {stdout_tail}")
        return stdout_tail or (f"Error executing function '{function_name}' (no response parsed)." + (f" Stderr: {stderr_tail}" if stderr_tail else ""))

    except subprocess.TimeoutExpired:
        error_message = f"Error: Function '{function_name}' timed out after 120 seconds."
        print(error_message)
        return error_message
    except Exception as e:
        error_message = f"An unexpected error occurred while executing function '{function_name}': {e}"
        print(error_message)
        return error_message



@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completion requests, including tool calls for MCP servers.
    """
    if not API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401
    try:
        openai_request = request.json
        print(f"Incoming Request: {pretty_json(openai_request)}")
        messages = openai_request.get('messages', [])

        # --- Prompt Engineering & Tool Control ---
        force_tools_enabled = True  # None: default, True: force, False: disable

        if messages:
            active_overrides = {}
            active_profile_name = None
            # Identify prompt profile by checking for triggers in the combined text of all messages
            full_prompt_text = " ".join(
                [m.get('content') for m in messages if isinstance(m.get('content'), str)]
            )

            if prompt_overrides:
                for profile_name, profile_data in prompt_overrides.items():
                    if isinstance(profile_data, dict):
                        for trigger in profile_data.get('triggers', []):
                            if trigger in full_prompt_text:
                                active_profile_name = profile_name
                                active_overrides = profile_data.get('overrides', {})
                                # If it's a commit message profile, do not send tools
                                if active_profile_name == "commit_message":
                                    force_tools_enabled = False
                                print(f"Prompt profile matched: '{profile_name}'")
                                break
                        if active_overrides:
                            break

            # Process all messages: apply overrides and check for tool keywords in the last message
            for i, message in enumerate(messages):
                content = message.get('content')
                if isinstance(content, str):
                    # Apply overrides from the matched profile
                    if active_overrides:
                        for find, replace in active_overrides.items():
                            if find in content:
                                content = content.replace(find, replace)

                    # Check for tool keywords only in the last message
                    if i == len(messages) - 1:
                        if '--nocmds' in content:
                            force_tools_enabled = False
                            content = content.replace('--nocmds', '').strip()

                    message['content'] = content
        # --- End Prompt Engineering ---

        COMPLETION_MODEL = openai_request.get('model', 'gemini-2.0-flash')
        system_instruction_text = None

        # Transform messages to Gemini format, merging consecutive messages of the same role
        gemini_contents = []
        if messages:
            # Map OpenAI roles to Gemini roles ('assistant' -> 'model', others -> 'user')
            mapped_messages = []
            for message in messages:
                role = "model" if message.get("role") == "assistant" else "user"
                content = message.get("content")

                gemini_parts = []
                # Content can be a string or a list of parts (for multimodal)
                if isinstance(content, str):
                    if content:  # Don't add empty messages
                        gemini_parts.append({"text": content})
                elif isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            image_part = _process_image_url(part.get("image_url", {}))
                            if image_part:
                                gemini_parts.append(image_part)

                    # Combine all text parts into a single text part for Gemini
                    if text_parts:
                        gemini_parts.insert(0, {"text": "\n".join(text_parts)})

                if gemini_parts:
                    mapped_messages.append({"role": role, "parts": gemini_parts})

            # Prepare system instruction to be sent via systemInstruction if tools are configured
            if mcp_function_declarations:
                system_instruction_text = (
                    "You are a helpful assistant with access to tools. When a user's request requires using a tool, "
                    "you MUST use the functionCall feature to invoke the appropriate tool. Do not simulate tool calls "
                    "or generate tool output as plain text. Always use the structured functionCall mechanism."
                )

            # Merge consecutive messages with the same role, as Gemini requires alternating roles
            if mapped_messages:
                gemini_contents.append(mapped_messages[0])
                for i in range(1, len(mapped_messages)):
                    if mapped_messages[i]['role'] == gemini_contents[-1]['role']:
                        # Append parts instead of just text to handle images correctly
                        gemini_contents[-1]['parts'].extend(mapped_messages[i]['parts'])
                    else:
                        gemini_contents.append(mapped_messages[i])

        # --- Token Management ---
        # Get the token limit for the requested model
        token_limit = get_model_input_limit(COMPLETION_MODEL)
        safe_limit = int(token_limit * TOKEN_ESTIMATE_SAFETY_MARGIN)

        # Truncate messages if they exceed the safe limit
        original_message_count = len(gemini_contents)
        truncated_gemini_contents = truncate_contents(gemini_contents, safe_limit)
        if len(truncated_gemini_contents) < original_message_count:
            print(f"Truncated conversation from {original_message_count} to {len(truncated_gemini_contents)} messages.")

        # Use a generator function to handle the streaming response and tool calls
        def generate():
            current_contents = truncated_gemini_contents.copy()

            while True:  # Loop to handle sequential tool calls
                request_data = {
                    "contents": current_contents
                }

                # Add tool declarations if MCP tools are configured and enabled for this request
                tools = create_tool_declarations()
                if tools and force_tools_enabled:
                    request_data["tools"] = tools
                    request_data["tool_config"] = {
                        "function_calling_config": {
                            "mode": "AUTO"
                        }
                    }

                GEMINI_STREAMING_URL = f"{UPSTREAM_URL}/v1beta/models/{COMPLETION_MODEL}:streamGenerateContent"
                headers = {
                    'Content-Type': 'application/json',
                    'X-goog-api-key': API_KEY
                }

                print(f"Outgoing Gemini Request URL: {GEMINI_STREAMING_URL}")
                print(f"Outgoing Gemini Request Data: {pretty_json(request_data)}")

                response = None
                try:
                    response = requests.post(
                        GEMINI_STREAMING_URL,
                        headers=headers,
                        json=request_data,
                        stream=True,
                        timeout=300
                    )
                    response.raise_for_status()
                except (HTTPError, ConnectionError, Timeout, RequestException) as e:
                    error_message = f"Error from upstream Gemini API: {e}"
                    print(error_message)
                    error_chunk = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": COMPLETION_MODEL,
                        "choices": [{"index": 0, "delta": {"content": error_message}, "finish_reason": "stop"}]
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Process the successful streaming response
                buffer = ""
                tool_calls = []
                model_response_parts = []
                decoder = json.JSONDecoder()

                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    if isinstance(chunk, str):
                        # Strip Server-Sent Events 'data: ' prefix to keep buffer JSON-clean
                        chunk = "\n".join(line[6:] if line.startswith("data: ") else line for line in chunk.splitlines())
                    buffer += chunk

                    while True:
                        # Find the start of a JSON object
                        start_index = buffer.find('{')
                        if start_index == -1:
                            # No start of object in buffer, wait for more data
                            # prevent unbounded growth on malformed input
                            if len(buffer) > 65536:
                                buffer = buffer[-32768:]
                            break

                        # Drop any non-JSON prefix (SSE noise, commas, brackets, newlines)
                        if start_index > 0:
                            buffer = buffer[start_index:]

                        # Try to decode a full JSON object from the current buffer
                        try:
                            json_data, end_index = decoder.raw_decode(buffer)
                        except json.JSONDecodeError:
                            # Need more data
                            break

                        # Advance the buffer to the remainder after the parsed object
                        buffer = buffer[end_index:]

                        # Process the valid JSON object
                        parts = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [])

                        # Handle metadata-only chunks gracefully
                        if not parts and 'usageMetadata' in json_data:
                            pass
                        else:
                            model_response_parts.extend(parts)
                            text_content = ""
                            for part in parts:
                                if 'text' in part:
                                    text_content += part['text']
                                if 'functionCall' in part:
                                    tool_calls.append(part['functionCall'])

                            if text_content:
                                chunk_response = {
                                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": COMPLETION_MODEL,
                                    "choices": [{"index": 0, "delta": {"content": text_content}, "finish_reason": None}]
                                }
                                yield f"data: {json.dumps(chunk_response)}\n\n"

                if not tool_calls:
                    # No tool calls, conversation is finished
                    break

                # --- Tool Call Execution ---
                print(f"Detected tool calls: {pretty_json(tool_calls)}")
                current_contents.append({
                    "role": "model",
                    "parts": model_response_parts
                })

                tool_response_parts = []
                for tool_call in tool_calls:
                    function_name = tool_call.get("name")
                    tool_args = tool_call.get("args")
                    output = execute_mcp_tool(function_name, tool_args)
                    # Try to parse tool output as JSON for structured responses; fall back to text
                    response_payload = None
                    if isinstance(output, str):
                        try:
                            response_payload = json.loads(output)
                        except json.JSONDecodeError:
                            response_payload = {"text": output}
                    else:
                        response_payload = output if output is not None else {"text": ""}

                    tool_response_parts.append({
                        "functionResponse": {
                            "name": function_name,
                            "response": response_payload
                        }
                    })

                current_contents.append({
                    "role": "tool",
                    "parts": tool_response_parts
                })
                # Loop will continue to call Gemini with tool results

            # Send the final chunk after the stream is finished
            final_chunk = {
                "id": f"chatcmpl-{os.urandom(12).hex()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": COMPLETION_MODEL,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            print(f"Final Proxy Response Chunk: {pretty_json(final_chunk)}")
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        error_message = f"An error occurred: {str(e)}"
        print(f"An error occurred during chat completion: {error_message}")

        # Формируем стандартный ответ с ошибкой
        error_response = {
            "error": {
                "message": error_message,
                "type": "server_error",
                "code": "500"
            }
        }
        return jsonify(error_response), 500


# The /v1/models endpoint remains the same
@app.route('/v1/models', methods=['GET'])
def list_models():
    """
    Fetches the list of available models from the Gemini API, caches the response,
    and formats it for the JetBrains AI Assist/OpenAI API.
    """
    if not API_KEY:
        return jsonify({"error": {"message": "API key not configured. Please set it on the root page.", "type": "invalid_request_error", "code": "api_key_not_set"}}), 401

    global cached_models_response

    try:
        if cached_models_response:
            return jsonify(cached_models_response)

        params = {"key": API_KEY}
        GEMINI_MODELS_URL = f"{UPSTREAM_URL}/v1beta/models"
        response = requests.get(GEMINI_MODELS_URL, params=params)
        response.raise_for_status()

        gemini_models_data = response.json()

        # Transform the Gemini model list to the OpenAI/JetBrains AI Assist format
        openai_models_list = []
        for model in gemini_models_data.get("models", []):
            # Only include models that support content generation
            if "generateContent" in model.get("supportedGenerationMethods", []):
                openai_models_list.append({
                    "id": model["name"].split("/")[-1],
                    "object": "model",
                    "created": 1677649553,
                    "owned_by": "google",
                    "permission": []
                })

        openai_response = {
            "object": "list",
            "data": openai_models_list
        }

        # Cache the successful response
        cached_models_response = openai_response
        return jsonify(openai_response)

    except requests.exceptions.RequestException as e:
        error_response = {"error": f"Error fetching models from Gemini API: {e}"}
        return jsonify(error_response), 500
    except Exception as e:
        error_response = {"error": f"Internal server error: {e}"}
        return jsonify(error_response), 500


def pretty_json(data):
    return json.dumps(data, ensure_ascii=False)


if __name__ == '__main__':
    print("Starting proxy server on http://0.0.0.0:8080...")
    app.run(host='0.0.0.0', port=8080)