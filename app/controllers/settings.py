"""
Flask routes for handling general application settings.
"""
from flask import Blueprint, request, redirect, url_for, jsonify

from app.config import config
from app import utils
from app.api_key_manager import api_key_manager

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/get_api_key_data', methods=['GET'])
def get_api_key_data():
    """Returns all key data as JSON."""
    return jsonify(api_key_manager.get_all_keys_data())


@settings_bp.route('/add_or_update_api_key', methods=['POST'])
def add_or_update_api_key():
    """Adds or updates an API key."""
    data = request.json
    key_id = data.get('key_id')
    key_value = data.get('key_value')
    set_active = data.get('set_active', False)

    if not key_id or not key_value:
        return jsonify({"error": "key_id and key_value are required"}), 400

    api_key_manager.add_or_update_key(key_id, key_value)
    if set_active:
        api_key_manager.set_active_key(key_id)
        config.reload_api_key()

    utils.log(f"API Key '{key_id}' has been added/updated.")
    return jsonify({"message": f"API Key '{key_id}' processed successfully."}), 200


@settings_bp.route('/set_active_api_key', methods=['POST'])
def set_active_api_key():
    """Sets the active API key."""
    data = request.json
    key_id = data.get('key_id')
    if not key_id:
        return jsonify({"error": "key_id is required"}), 400

    if api_key_manager.set_active_key(key_id):
        config.reload_api_key()
        utils.log(f"Active API Key set to '{key_id}'.")
        return jsonify({"message": f"Active API Key set to '{key_id}'."}), 200
    return jsonify({"error": f"API Key ID '{key_id}' not found."}), 404


@settings_bp.route('/delete_api_key', methods=['POST'])
def delete_api_key():
    """Deletes an API key."""
    data = request.json
    key_id = data.get('key_id')
    if not key_id:
        return jsonify({"error": "key_id is required"}), 400

    if api_key_manager.delete_key(key_id):
        config.reload_api_key()
        utils.log(f"API Key '{key_id}' has been deleted.")
        return jsonify({"message": f"API Key '{key_id}' deleted."}), 200
    return jsonify({"error": f"API Key ID '{key_id}' not found."}), 404

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
    """Enables or disables verbose and debug client logging."""
    verbose_logging_enabled = request.form.get('verbose_logging') == 'on'
    debug_client_logging_enabled = request.form.get('debug_client_logging') == 'on'
    utils.set_verbose_logging(verbose_logging_enabled)
    utils.set_debug_client_logging(debug_client_logging_enabled)
    return redirect(url_for('web_ui.index', _anchor='configuration'))
