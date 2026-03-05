from flask import Blueprint, request, redirect, url_for, jsonify
from app.utils.core import mcp_handler, settings_logic
mcp_settings_bp = Blueprint('mcp_settings', __name__)
@mcp_settings_bp.route('/set_mcp_config', methods=['POST'])
def set_mcp_config():
    error = settings_logic.handle_set_mcp_config(request.form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='mcp'))
@mcp_settings_bp.route('/mcp_tool_info', methods=['POST'])
def mcp_tool_info():
    tool_config = request.json
    if not tool_config:
        return jsonify({"error": "Invalid request body"}), 400

    result = mcp_handler.fetch_mcp_tool_list(tool_config)
    return jsonify(result)
@mcp_settings_bp.route('/set_mcp_general_settings', methods=['POST'])
def set_mcp_general_settings():
    settings_logic.handle_set_mcp_general_settings(request.form)
    return redirect(url_for('web_ui.index', _anchor='mcp'))

@mcp_settings_bp.route('/api/mcp/list', methods=['GET'])
async def list_mcp_tools_and_methods():
    """
    Returns a list of all registered FastMCP tools.
    """
    from app.core.mcp_server import mcp
    tools_structure = {
        "built_in": [],
        "servers": {}
    }
    
    # FastMCP state might not be fully synced in ASGI child processes. 
    # Force a sync if we have declarations but they didn't map.
    if hasattr(mcp, "_tools") and len(mcp._tools) < len(mcp_handler.mcp_function_declarations):
        mcp_handler.load_mcp_config()
        
    tools = await mcp.list_tools()
    for t in tools:
        tools_structure["built_in"].append({
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters
        })
             
    return jsonify(tools_structure)

@mcp_settings_bp.route('/api/mcp/debug', methods=['GET'])
async def list_mcp_tools_debug():
    from app.core.mcp_server import mcp
    tools = await mcp.list_tools()
    tools_list = [{"name": t.name, "desc": t.description} for t in tools]
    return jsonify({
        "mcp_tools": tools_list,
        "fastmcp_internal": getattr(mcp, "_tools", "N/A - unsupported attribute") 
    })

@mcp_settings_bp.route('/api/mcp/definition', methods=['POST'])
async def get_mcp_definition_for_prompt():
    """
    Returns the JSON definition for specific tools to be used in a prompt.
    Input: { "functions": ["func1", "func2"] } or { "functions": ["*"] }
    """
    from app.core.mcp_server import mcp
    data = request.json or {}
    functions = data.get("functions", [])
    
    if not functions:
        return jsonify({"error": "No functions specified"}), 400
        
    tools = await mcp.list_tools()
    declarations_list = []
    
    for t in tools:
        if "*" in functions or t.name in functions:
            declarations_list.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters
            })
            
    return jsonify({"functionDeclarations": declarations_list})

@mcp_settings_bp.route('/api/mcp/servers', methods=['GET'])
def get_mcp_servers_api():
    config_data = {}
    import os, json
    if os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        try:
            with open(mcp_handler.MCP_CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify(config_data.get("mcpServers", {}))

@mcp_settings_bp.route('/api/mcp/servers', methods=['POST'])
def save_mcp_servers_api():
    new_servers = request.json
    if not isinstance(new_servers, dict):
        return jsonify({"error": "Invalid payload format, expected a dictionary of servers"}), 400
    
    import os, json
    config_data = {}
    if os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        try:
            with open(mcp_handler.MCP_CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
        except Exception:
            pass
            
    config_data["mcpServers"] = new_servers
    
    try:
        os.makedirs(os.path.dirname(mcp_handler.MCP_CONFIG_FILE), exist_ok=True)
        with open(mcp_handler.MCP_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        mcp_handler.load_mcp_config()
        return jsonify({"success": True, "message": "MCP servers updated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500