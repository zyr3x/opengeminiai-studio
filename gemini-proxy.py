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

app = Flask(__name__)

# Load environment variables from .env file at startup
load_dotenv()

# --- MCP Tool Configuration ---
mcp_config = {}
MCP_CONFIG_FILE = 'mcp_config.json'
mcp_function_declarations = []  # A flat list of all function declarations from all tools
mcp_function_to_tool_map = {}   # Maps a function name to its parent tool name (from mcpServers)

def get_declarations_from_tool(tool_name, tool_info):
    """Fetches function declaration schema(s) from an MCP tool using MCP protocol."""
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

                        # Convert MCP input schema to Gemini parameters format
                        if "inputSchema" in tool:
                            schema = tool["inputSchema"]
                            if schema.get("type") == "object":
                                # Use JSON Schema types as expected by Gemini (lowercase)
                                declaration["parameters"] = {
                                    "type": "object",
                                    "properties": {}
                                }

                                for prop_name, prop_def in schema.get("properties", {}).items():
                                    # Normalize to valid JSON Schema types
                                    param_type = str(prop_def.get("type", "string")).lower()
                                    if param_type not in {"string", "number", "integer", "boolean", "array", "object"}:
                                        param_type = "string"

                                    declaration["parameters"]["properties"][prop_name] = {
                                        "type": param_type,
                                        "description": prop_def.get("description", f"Parameter {prop_name}")
                                    }

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
    global mcp_config, mcp_function_declarations, mcp_function_to_tool_map
    mcp_function_declarations = []
    mcp_function_to_tool_map = {}

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
            <form action="/set_mcp_config" method="POST">
                <label for="mcp_config"><b>MCP JSON Config:</b></label><br>
                <textarea id="mcp_config" name="mcp_config" rows="15">{current_mcp_config_str or pretty_json(default_mcp_config)}</textarea><br><br>
                <input type="submit" value="Save MCP Config">
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
            <pre><code>export API_KEY="YOUR_GEMINI_API_KEY"
export UPSTREAM_URL="https://generativelanguage.googleapis.com"</code></pre>
            <p>Then, run the server:</p>
            <pre><code>python gemini-proxy.py</code></pre>
            <p>The server will start on <code>http://0.0.0.0:8080</code> by default.</p>

            <h3>2. Configure JetBrains AI Assistant</h3>
            <p>To use this proxy with JetBrains IDEs:</p>
            <ol>
                <li>Open AI Assistant settings (<code>Settings</code> > <code>Tools</code> > <code>AI Assistant</code>).</li>
                <li>Select the "Custom" service.</li>
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

        mcp_call_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": function_name,
                "arguments": tool_args if tool_args is not None else {}
            }
        }

        # Send initialize -> notifications/initialized -> tools/call in a single stdio session
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        input_data = (
            json.dumps(mcp_init_request) + "\n" +
            json.dumps(initialized_notification) + "\n" +
            json.dumps(mcp_call_request) + "\n"
        )

        process = subprocess.run(
            command,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=120
        )

        if process.returncode != 0:
            error_message = f"Error executing function '{function_name}': Command failed with exit code {process.returncode}.\nStdout: {process.stdout}\nStderr: {process.stderr}"
            print(error_message)
            return error_message

        # Parse MCP response - look for tools/call response (id == 1)
        lines = process.stdout.strip().split('\n')

        for line in lines:
            if not line.strip():
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
                            return result_text if result_text else str(response["result"])
                        else:
                            return str(response["result"])
                    elif "error" in response:
                        return f"MCP Error: {response['error'].get('message', 'Unknown error')}"
            except json.JSONDecodeError:
                continue

        # Fallback: return raw stdout if no proper MCP response found
        print(f"Function '{function_name}' stdout: {process.stdout}")
        if process.stderr:
            print(f"Function '{function_name}' stderr: {process.stderr}")
        return process.stdout

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

                # Add tool declarations if MCP tools are configured
                tools = create_tool_declarations()
                if tools:
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

                for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                    if isinstance(chunk, str):
                        # Strip Server-Sent Events 'data: ' prefix to keep buffer JSON-clean
                        chunk = "\n".join(line[6:] if line.startswith("data: ") else line for line in chunk.splitlines())
                    buffer += chunk

                    while True:
                        brace_level = 0
                        start_index = buffer.find('{')
                        if start_index == -1:
                            # No start of object in buffer, wait for more data
                            break

                        end_index = -1
                        # Find the corresponding closing brace for the first opening brace
                        for i in range(start_index, len(buffer)):
                            if buffer[i] == '{':
                                brace_level += 1
                            elif buffer[i] == '}':
                                brace_level -= 1

                            if brace_level == 0:
                                end_index = i
                                break

                        if end_index != -1:
                            # We have a complete potential JSON object
                            obj_str = buffer[start_index : end_index + 1]
                            try:
                                json_data = json.loads(obj_str)

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

                                # Remove processed object from buffer and check for more
                                buffer = buffer[end_index + 1:]

                            except (json.JSONDecodeError, KeyError, IndexError) as e:
                                print(f"Could not process potential JSON object: '{obj_str}'. Error: {e}. Discarding and continuing.")
                                # Discard the malformed part to avoid an infinite loop
                                buffer = buffer[end_index + 1:]
                        else:
                            # Incomplete object in buffer, wait for more data
                            break

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
    return json.dumps(data, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    print("Starting proxy server on http://0.0.0.0:8080...")
    app.run(host='0.0.0.0', port=8080)