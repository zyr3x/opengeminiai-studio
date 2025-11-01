from flask import Blueprint, request, redirect, url_for
from app.utils.core import settings_logic
prompt_settings_bp = Blueprint('prompt_settings', __name__)
@prompt_settings_bp.route('/set_prompt_config', methods=['POST'])
def set_prompt_config():
    error = settings_logic.handle_set_prompt_config(request.form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))
@prompt_settings_bp.route('/set_system_prompt_config', methods=['POST'])
def set_system_prompt_config():
    error = settings_logic.handle_set_system_prompt_config(request.form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))