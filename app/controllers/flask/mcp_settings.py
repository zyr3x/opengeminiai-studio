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
