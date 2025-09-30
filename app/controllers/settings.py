"""
Flask routes for handling general application settings.
"""
from flask import Blueprint, request, redirect, url_for

from app.config import config
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
