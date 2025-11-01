from flask import Blueprint, request, redirect, url_for, jsonify
from app.utils.core.api_key_manager import api_key_manager
from app.utils.core import settings_logic
settings_bp = Blueprint('settings', __name__)
@settings_bp.route('/get_api_key_data', methods=['GET'])
def get_api_key_data():
    return jsonify(api_key_manager.get_all_keys_data())
@settings_bp.route('/add_or_update_api_key', methods=['POST'])
def add_or_update_api_key():
    message, status_code = settings_logic.handle_add_or_update_api_key(request.json)
    return jsonify(message), status_code
@settings_bp.route('/set_active_api_key', methods=['POST'])
def set_active_api_key():
    message, status_code = settings_logic.handle_set_active_api_key(request.json)
    return jsonify(message), status_code
@settings_bp.route('/delete_api_key', methods=['POST'])
def delete_api_key():
    message, status_code = settings_logic.handle_delete_api_key(request.json)
    return jsonify(message), status_code
@settings_bp.route('/set_api_key', methods=['POST'])
def set_api_key():
    settings_logic.handle_set_api_key_form(request.form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
@settings_bp.route('/set_logging', methods=['POST'])
def set_logging():
    settings_logic.handle_set_logging(request.form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
@settings_bp.route('/set_context_settings', methods=['POST'])
def set_context_settings():
    settings_logic.handle_set_context_settings(request.form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
@settings_bp.route('/set_streaming_settings', methods=['POST'])
def set_streaming_settings():
    settings_logic.handle_set_streaming_settings(request.form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
@settings_bp.route('/set_security_settings', methods=['POST'])
def set_security_settings():
    settings_logic.handle_set_security_settings(request.form)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
