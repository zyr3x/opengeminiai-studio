"""
Flask routes for handling MCP (Model Configuration Provider) settings.
"""
import json
import os
from flask import Blueprint, request, redirect, url_for, jsonify

from app import mcp_handler
from app import utils

mcp_settings_bp = Blueprint('mcp_settings', __name__)

@mcp_settings_bp.route('/set_mcp_config', methods=['POST'])
def set_mcp_config():
    """Saves MCP tool configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('mcp_config')
    if config_str:
        try:
            json.loads(config_str.strip())
            with open(mcp_handler.MCP_CONFIG_FILE, 'w') as f:
                f.write(config_str.strip())
            utils.log(f"MCP config updated and saved to {mcp_handler.MCP_CONFIG_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in MCP config: {e}")
            return redirect(url_for('web_ui.index', _anchor='mcp'))
    elif os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        os.remove(mcp_handler.MCP_CONFIG_FILE)
        utils.log("MCP config cleared.")

    mcp_handler.load_mcp_config()
    return redirect(url_for('web_ui.index', _anchor='mcp'))


@mcp_settings_bp.route('/mcp_tool_info', methods=['POST'])
def mcp_tool_info():
    """
    Fetches tool declarations from a single MCP tool based on the provided configuration.
    This is used for UI checks and does not affect the saved configuration.
    """
    tool_config = request.json
    if not tool_config:
        return jsonify({"error": "Invalid request body"}), 400

    result = mcp_handler.fetch_mcp_tool_list(tool_config)
    return jsonify(result)
