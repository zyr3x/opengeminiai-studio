"""
Quart routes for handling general application settings.
"""
from quart import Blueprint, request, redirect, url_for, jsonify
from app.config import config
from app.utils.core import tools as utils
from app.utils.core.api_key_manager import api_key_manager

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/get_api_key_data', methods=['GET'])
def get_api_key_data():
    """Returns all key data as JSON."""
    return jsonify(api_key_manager.get_all_keys_data())


@settings_bp.route('/add_or_update_api_key', methods=['POST'])
async def add_or_update_api_key():
    """Adds or updates an API key."""
    data = await request.json
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
async def set_active_api_key():
    """Sets the active API key."""
    data = await request.json
    key_id = data.get('key_id')
    if not key_id:
        return jsonify({"error": "key_id is required"}), 400

    if api_key_manager.set_active_key(key_id):
        config.reload_api_key()
        utils.log(f"Active API Key set to '{key_id}'.")
        return jsonify({"message": f"Active API Key set to '{key_id}'."}), 200
    return jsonify({"error": f"API Key ID '{key_id}' not found."}), 404


@settings_bp.route('/delete_api_key', methods=['POST'])
async def delete_api_key():
    """Deletes an API key."""
    data = await request.json
    key_id = data.get('key_id')
    if not key_id:
        return jsonify({"error": "key_id is required"}), 400

    if api_key_manager.delete_key(key_id):
        config.reload_api_key()
        utils.log(f"API Key '{key_id}' has been deleted.")
        return jsonify({"message": f"API Key '{key_id}' deleted."}), 200
    return jsonify({"error": f"API Key ID '{key_id}' not found."}), 404

@settings_bp.route('/set_api_key', methods=['POST'])
async def set_api_key():
    """
    Sets the API_KEY from a web form and saves it to the .env file for persistence.
    """
    form = await request.form
    new_key = form.get('api_key')
    if new_key:
        config.set_api_key(new_key)
        utils.log("API Key has been updated via web interface and saved to .env file.")
        utils.cached_models_response = None
        utils.model_info_cache.clear()
        utils.log("Caches cleared due to API key change.")
    return redirect(url_for('web_ui.index', _anchor='configuration'))

@settings_bp.route('/set_logging', methods=['POST'])
async def set_logging():
    """Enables or disables verbose and debug client logging."""
    form = await request.form
    verbose_logging_enabled = form.get('verbose_logging') == 'on'
    debug_client_logging_enabled = form.get('debug_client_logging') == 'on'
    utils.set_verbose_logging(verbose_logging_enabled)
    utils.set_debug_client_logging(debug_client_logging_enabled)
    return redirect(url_for('web_ui.index', _anchor='configuration'))

@settings_bp.route('/set_context_settings', methods=['POST'])
async def set_context_settings():
    """Updates context management settings and saves them to .env file."""
    from dotenv import set_key
    form = await request.form
    
    # Get values from form
    selective_context_enabled = form.get('selective_context_enabled') == 'on'
    context_min_relevance_score = form.get('context_min_relevance_score', '0.3')
    context_always_keep_recent = form.get('context_always_keep_recent', '15')
    
    # Update .env file
    env_file = '.env'
    set_key(env_file, 'SELECTIVE_CONTEXT_ENABLED', 'true' if selective_context_enabled else 'false')
    set_key(env_file, 'CONTEXT_MIN_RELEVANCE_SCORE', str(context_min_relevance_score))
    set_key(env_file, 'CONTEXT_ALWAYS_KEEP_RECENT', str(context_always_keep_recent))
    
    # Update config in memory
    config.SELECTIVE_CONTEXT_ENABLED = selective_context_enabled
    config.CONTEXT_MIN_RELEVANCE_SCORE = float(context_min_relevance_score)
    config.CONTEXT_ALWAYS_KEEP_RECENT = int(context_always_keep_recent)
    
    utils.log(f"Context settings updated: selective={selective_context_enabled}, min_score={context_min_relevance_score}, keep_recent={context_always_keep_recent}")
    return redirect(url_for('web_ui.index', _anchor='configuration'))

@settings_bp.route('/set_security_settings', methods=['POST'])
async def set_security_settings():
    """Updates security settings and saves them to .env file."""
    from dotenv import set_key
    import os
    form = await request.form
    
    # Get values from form
    allowed_code_paths = form.get('allowed_code_paths', '').strip()
    
    # Update .env file
    env_file = '.env'
    set_key(env_file, 'ALLOWED_CODE_PATHS', allowed_code_paths)
    
    # Update config in memory
    if allowed_code_paths:
        config.ALLOWED_CODE_PATHS = [
            os.path.realpath(os.path.expanduser(p.strip())) 
            for p in allowed_code_paths.split(',') 
            if p.strip()
        ]
    else:
        config.ALLOWED_CODE_PATHS = []
    
    utils.log(f"Security settings updated: allowed_code_paths={config.ALLOWED_CODE_PATHS}")
    return redirect(url_for('web_ui.index', _anchor='configuration'))
