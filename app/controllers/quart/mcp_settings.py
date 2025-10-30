"""
Quart routes for handling MCP (Model Configuration Provider) settings.
"""
from quart import Blueprint, request, redirect, url_for, jsonify
from app.utils.core import mcp_handler, settings_logic

mcp_settings_bp = Blueprint('mcp_settings', __name__)


@mcp_settings_bp.route('/set_mcp_config', methods=['POST'])
async def set_mcp_config():
    """Saves MCP tool configuration from web form to a JSON file and reloads it."""
    form = await request.form
    error = settings_logic.handle_set_mcp_config(form)
    if error:
        # Optionally, flash the error message to the user
        pass
    return redirect(url_for('web_ui.index', _anchor='mcp'))


@mcp_settings_bp.route('/mcp_tool_info', methods=['POST'])
async def mcp_tool_info():
    """
    Fetches tool declarations from a single MCP tool based on the provided configuration.
    This is used for UI checks and does not affect the saved configuration.
    """
    tool_config = await request.json
    if not tool_config:
        return jsonify({"error": "Invalid request body"}), 400

    result = mcp_handler.fetch_mcp_tool_list(tool_config)
    return jsonify(result)


@mcp_settings_bp.route('/set_mcp_general_settings', methods=['POST'])
async def set_mcp_general_settings():
    """
    Sets general MCP settings, like enabling/disabling all tools.
    """
    form = await request.form
    settings_logic.handle_set_mcp_general_settings(form)
    return redirect(url_for('web_ui.index', _anchor='mcp'))
