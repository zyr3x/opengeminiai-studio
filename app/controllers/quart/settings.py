"""
Quart routes for handling general application settings.
"""
from quart import Blueprint, request, redirect, url_for, jsonify
from app.utils.core.api_key_manager import api_key_manager
from app.utils.core import settings_logic

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/get_api_key_data', methods=['GET'])
def get_api_key_data():
    """Returns all key data as JSON."""
    return jsonify(api_key_manager.get_all_keys_data())


@settings_bp.route('/add_or_update_api_key', methods=['POST'])
async def add_or_update_api_key():
    """Adds or updates an API key."""
    data = await request.json
    message, status_code = settings_logic.handle_add_or_update_api_key(data)
    return jsonify(message), status_code


@settings_bp.route('/set_active_api_key', methods=['POST'])
async def set_active_api_key():
    """Sets the active API key."""
    data = await request.json
    message, status_code = settings_logic.handle_set_active_api_key(data)
    return jsonify(message), status_code


@settings_bp.route('/delete_api_key', methods=['POST'])
async def delete_api_key():
    """Deletes an API key."""
    data = await request.json
    message, status_code = settings_logic.handle_delete_api_key(data)
    return jsonify(message), status_code


@settings_bp.route('/set_api_key', methods=['POST'])
async def set_api_key():
    """
    Sets the API_KEY from a web form and saves it to the .env file for persistence.
    """
    form = await request.form
    settings_logic.handle_set_api_key_form(form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_logging', methods=['POST'])
async def set_logging():
    """Enables or disables verbose and debug client logging."""
    form = await request.form
    settings_logic.handle_set_logging(form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_context_settings', methods=['POST'])
async def set_context_settings():
    """Updates context management settings and saves them to .env file."""
    form = await request.form
    settings_logic.handle_set_context_settings(form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_streaming_settings', methods=['POST'])
async def set_streaming_settings():
    """Updates streaming settings and saves them to .env file."""
    form = await request.form
    settings_logic.handle_set_streaming_settings(form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))


@settings_bp.route('/set_security_settings', methods=['POST'])
async def set_security_settings():
    """Updates security settings and saves them to .env file."""
    form = await request.form
    settings_logic.handle_set_security_settings(form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
