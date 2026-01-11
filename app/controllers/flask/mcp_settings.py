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
def list_mcp_tools_and_methods():
    """
    Returns a structured list of all available MCP tools and their methods.
    """
    tools_structure = {
        "built_in": [],
        "servers": {}
    }
    
    # Built-ins
    for decl in mcp_handler.BUILTIN_DECLARATIONS:
        tools_structure["built_in"].append({
            "name": decl.get("name"),
            "description": decl.get("description"),
            "parameters": decl.get("parameters")
        })

    # Servers
    servers = mcp_handler.mcp_config.get("mcpServers", {})
    for server_name, server_config in servers.items():
        safe_config = server_config.copy()
        if 'env' in safe_config:
             safe_config['env'] = {k: '***' if 'KEY' in k.upper() or 'SECRET' in k.upper() else v for k,v in safe_config['env'].items()}
             
        tools_structure["servers"][server_name] = {
            "config": safe_config,
            "methods": []
        }

    # Map methods
    for decl in mcp_handler.mcp_function_declarations:
        func_name = decl.get("name")
        tool_name = mcp_handler.mcp_function_to_tool_map.get(func_name)
        
        if tool_name == mcp_handler.BUILTIN_TOOL_NAME:
            continue
            
        if tool_name and tool_name in tools_structure["servers"]:
             tools_structure["servers"][tool_name]["methods"].append({
                "name": func_name,
                "description": decl.get("description"),
                "parameters": decl.get("parameters")
             })
             
    return jsonify(tools_structure)

@mcp_settings_bp.route('/api/mcp/definition', methods=['POST'])
def get_mcp_definition_for_prompt():
    """
    Returns the JSON definition for specific tools to be used in a prompt.
    Input: { "functions": ["func1", "func2"] } or { "functions": ["*"] }
    """
    data = request.json or {}
    functions = data.get("functions", [])
    
    if not functions:
        return jsonify({"error": "No functions specified"}), 400
        
    declarations_list = mcp_handler.create_tool_declarations_from_list(functions)
    
    if declarations_list:
        return jsonify(declarations_list[0])
    
    return jsonify({"functionDeclarations": []})