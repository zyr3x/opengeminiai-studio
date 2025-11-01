from quart import Blueprint, request, redirect, url_for
from app.utils.core import settings_logic

prompt_settings_bp = Blueprint('prompt_settings', __name__)


@prompt_settings_bp.route('/set_prompt_config', methods=['POST'])
async def set_prompt_config():
    form = await request.form
    error = settings_logic.handle_set_prompt_config(form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))


@prompt_settings_bp.route('/set_system_prompt_config', methods=['POST'])
async def set_system_prompt_config():
    form = await request.form
    error = settings_logic.handle_set_system_prompt_config(form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))


@prompt_settings_bp.route('/set_agent_prompt_config', methods=['POST'])
async def set_agent_prompt_config():
    form = await request.form
    error = settings_logic.handle_set_agent_prompt_config(form)
    if error:
        pass
    return redirect(url_for('web_ui.index', _anchor='prompts'))