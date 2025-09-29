"""
Flask routes for handling application settings and configuration.
"""
import json
import os
from flask import Blueprint, request, redirect, url_for

from app.config import config
from app import mcp_handler
from app import utils

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/set_api_key', methods=['POST'])
def set_api_key():
    """
    Sets the API_KEY from a web form and saves it to the .env file for persistence.
    """
    new_key = request.form.get('api_key')
    if new_key:
        config.set_api_key(new_key)
        utils.log("API Key has been updated via web interface and saved to .env file.")
        utils.cached_models_response = None
        utils.model_info_cache.clear()
        utils.log("Caches cleared due to API key change.")
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_logging', methods=['POST'])
def set_logging():
    """Enables or disables verbose logging."""
    logging_enabled = request.form.get('verbose_logging') == 'on'
    utils.set_verbose_logging(logging_enabled)
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_mcp_config', methods=['POST'])
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

@settings_bp.route('/set_prompt_config', methods=['POST'])
def set_prompt_config():
    """Saves prompt override configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('prompt_overrides')
    if config_str:
        try:
            json.loads(config_str.strip())
            with open(utils.PROMPT_OVERRIDES_FILE, 'w') as f:
                f.write(config_str.strip())
            utils.log(f"Prompt overrides updated and saved to {utils.PROMPT_OVERRIDES_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in prompt overrides: {e}")
            return redirect(url_for('web_ui.index', _anchor='prompts'))
    elif os.path.exists(utils.PROMPT_OVERRIDES_FILE):
        os.remove(utils.PROMPT_OVERRIDES_FILE)
        utils.log("Prompt overrides config cleared.")

    utils.load_prompt_config()
    return redirect(url_for('web_ui.index', _anchor='prompts'))
