"""
Flask routes for handling prompt override settings.
"""
import json
import os
from flask import Blueprint, request, redirect, url_for

from app import utils

prompt_settings_bp = Blueprint('prompt_settings', __name__)

@prompt_settings_bp.route('/set_prompt_config', methods=['POST'])
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

@prompt_settings_bp.route('/set_system_prompt_config', methods=['POST'])
def set_system_prompt_config():
    """Saves system prompt configuration from web form to a JSON file and reloads it."""
    config_str = request.form.get('system_prompts')
    if config_str:
        try:
            json.loads(config_str.strip())
            with open(utils.SYSTEM_PROMPTS_FILE, 'w') as f:
                f.write(config_str.strip())
            utils.log(f"System prompts updated and saved to {utils.SYSTEM_PROMPTS_FILE}.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in system prompts: {e}")
            return redirect(url_for('web_ui.index', _anchor='prompts'))
    elif os.path.exists(utils.SYSTEM_PROMPTS_FILE):
        os.remove(utils.SYSTEM_PROMPTS_FILE)
        utils.log("System prompts config cleared.")

    utils.load_system_prompt_config()
    return redirect(url_for('web_ui.index', _anchor='prompts'))