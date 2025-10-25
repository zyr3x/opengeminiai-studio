"""
Flask routes for handling prompt override settings.
"""
from flask import Blueprint, request, redirect, url_for

from app import utils

prompt_settings_bp = Blueprint('prompt_settings', __name__)

@prompt_settings_bp.route('/set_prompt_config', methods=['POST'])
def set_prompt_config():
    """Saves prompt override configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('prompt_overrides', '')

    try:
        utils.save_config_to_file(
            config_str=config_str,
            file_path=utils.PROMPT_OVERRIDES_FILE,
            config_name="Prompt overrides"
        )
    except ValueError as e:
        utils.log(f"Error: {e}")
        return redirect(url_for('web_ui.index', _anchor='prompts'))

    utils.load_prompt_config()
    return redirect(url_for('web_ui.index', _anchor='prompts'))

@prompt_settings_bp.route('/set_system_prompt_config', methods=['POST'])
def set_system_prompt_config():
    """Saves system prompt configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('system_prompts', '')

    try:
        utils.save_config_to_file(
            config_str=config_str,
            file_path=utils.SYSTEM_PROMPTS_FILE,
            config_name="System prompts"
        )
    except ValueError as e:
        utils.log(f"Error: {e}")
        return redirect(url_for('web_ui.index', _anchor='prompts'))

    utils.load_system_prompt_config()
    return redirect(url_for('web_ui.index', _anchor='prompts'))