"""
Quart routes for handling prompt override settings.
"""
from quart import Blueprint, request, redirect, url_for
from app.utils.core import settings_logic

prompt_settings_bp = Blueprint('prompt_settings', __name__)


@prompt_settings_bp.route('/set_prompt_config', methods=['POST'])
async def set_prompt_config():
    """Saves prompt override configuration from web form to a JSON file and reloads it."""
    form = await request.form
    error = settings_logic.handle_set_prompt_config(form)
    if error:
        # Optionally, flash the error message
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))


@prompt_settings_bp.route('/set_system_prompt_config', methods=['POST'])
async def set_system_prompt_config():
    """Saves system prompt configuration from web form to a JSON file and reloads it."""
    form = await request.form
    error = settings_logic.handle_set_system_prompt_config(form)
    if error:
        # Optionally, flash the error message
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))