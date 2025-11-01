from app.config import config
from app.utils.core import tools as utils, mcp_handler
from app.utils.core.api_key_manager import api_key_manager
from dotenv import set_key
import os
def handle_add_or_update_api_key(data):
    key_id = data.get('key_id')
    key_value = data.get('key_value')
    set_active = data.get('set_active', False)

    if not key_id or not key_value:
        return {"error": "key_id and key_value are required"}, 400

    api_key_manager.add_or_update_key(key_id, key_value)
    if set_active:
        api_key_manager.set_active_key(key_id)
        config.reload_api_key()

    utils.log(f"API Key '{key_id}' has been added/updated.")
    return {"message": f"API Key '{key_id}' processed successfully."}, 200
def handle_set_active_api_key(data):
    key_id = data.get('key_id')
    if not key_id:
        return {"error": "key_id is required"}, 400

    if api_key_manager.set_active_key(key_id):
        config.reload_api_key()
        utils.log(f"Active API Key set to '{key_id}'.")
        return {"message": f"Active API Key set to '{key_id}'."}, 200
    return {"error": f"API Key ID '{key_id}' not found."}, 404
def handle_delete_api_key(data):
    key_id = data.get('key_id')
    if not key_id:
        return {"error": "key_id is required"}, 400

    if api_key_manager.delete_key(key_id):
        config.reload_api_key()
        utils.log(f"API Key '{key_id}' has been deleted.")
        return {"message": f"API Key '{key_id}' deleted."}, 200
    return {"error": f"API Key ID '{key_id}' not found."}, 404
def handle_set_api_key_form(form):
    new_key = form.get('api_key')
    if new_key:
        config.set_api_key(new_key)
        utils.log("API Key has been updated via web interface and saved to .env file.")
        utils.cached_models_response = None
        utils.model_info_cache.clear()
        utils.log("Caches cleared due to API key change.")
def handle_set_logging(form):
    verbose_logging_enabled = form.get('verbose_logging') == 'on'
    debug_client_logging_enabled = form.get('debug_client_logging') == 'on'
    utils.set_verbose_logging(verbose_logging_enabled)
    utils.set_debug_client_logging(debug_client_logging_enabled)
def handle_set_context_settings(form):
    selective_context_enabled = form.get('selective_context_enabled') == 'on'
    context_min_relevance_score = form.get('context_min_relevance_score', '0.3')
    context_always_keep_recent = form.get('context_always_keep_recent', '15')
    min_context_caching_tokens = form.get('min_context_caching_tokens', '512')

    env_file = '.env'
    set_key(env_file, 'SELECTIVE_CONTEXT_ENABLED', 'true' if selective_context_enabled else 'false')
    set_key(env_file, 'CONTEXT_MIN_RELEVANCE_SCORE', str(context_min_relevance_score))
    set_key(env_file, 'CONTEXT_ALWAYS_KEEP_RECENT', str(context_always_keep_recent))
    set_key(env_file, 'MIN_CONTEXT_CACHING_TOKENS', str(min_context_caching_tokens))

    config.SELECTIVE_CONTEXT_ENABLED = selective_context_enabled
    config.CONTEXT_MIN_RELEVANCE_SCORE = float(context_min_relevance_score)
    config.CONTEXT_ALWAYS_KEEP_RECENT = int(context_always_keep_recent)
    config.MIN_CONTEXT_CACHING_TOKENS = int(min_context_caching_tokens)
    utils.log(f"Context settings updated: selective={selective_context_enabled}, min_score={context_min_relevance_score}, keep_recent={context_always_keep_recent}, min_cache_tokens={min_context_caching_tokens}")
def handle_set_streaming_settings(form):
    streaming_enabled = form.get('streaming_enabled') == 'on'
    streaming_progress_enabled = form.get('streaming_progress_enabled') == 'on'

    env_file = '.env'
    set_key(env_file, 'STREAMING_ENABLED', 'true' if streaming_enabled else 'false')
    set_key(env_file, 'STREAMING_PROGRESS_ENABLED', 'true' if streaming_progress_enabled else 'false')

    config.STREAMING_ENABLED = streaming_enabled
    config.STREAMING_PROGRESS_ENABLED = streaming_progress_enabled
    utils.log(f"Streaming settings updated: enabled={streaming_enabled}, progress_enabled={streaming_progress_enabled}")
def handle_set_security_settings(form):
    allowed_code_paths = form.get('allowed_code_paths', '').strip()
    max_code_injection_size_kb = form.get('max_code_injection_size_kb', '128')

    env_file = '.env'
    set_key(env_file, 'ALLOWED_CODE_PATHS', allowed_code_paths)
    set_key(env_file, 'MAX_CODE_INJECTION_SIZE_KB', str(max_code_injection_size_kb))

    if allowed_code_paths:
        config.ALLOWED_CODE_PATHS = [
            os.path.realpath(os.path.expanduser(p.strip()))
            for p in allowed_code_paths.split(',')
            if p.strip()
        ]
    else:
        config.ALLOWED_CODE_PATHS = []

    config.MAX_CODE_INJECTION_SIZE_KB = int(max_code_injection_size_kb)
    utils.log(f"Security settings updated: allowed_code_paths={config.ALLOWED_CODE_PATHS}, max_code_injection_size_kb={config.MAX_CODE_INJECTION_SIZE_KB}")
def handle_set_mcp_config(form):
    config_str = form.get('mcp_config', '')
    try:
        utils.save_config_to_file(
            config_str=config_str,
            file_path=mcp_handler.MCP_CONFIG_FILE,
            config_name="MCP config"
        )
        mcp_handler.load_mcp_config()
        return None
    except ValueError as e:
        utils.log(f"Error: {e}")
        return e
def handle_set_mcp_general_settings(form):
    disable_all_tools_enabled = form.get('disable_all_mcp_tools') == 'on'
    mcp_handler.set_disable_all_mcp_tools(disable_all_tools_enabled)
    mcp_handler.load_mcp_config()
def handle_set_prompt_config(form):
    config_str = form.get('prompt_overrides', '')
    try:
        utils.save_config_to_file(
            config_str=config_str,
            file_path=utils.PROMPT_OVERRIDES_FILE,
            config_name="Prompt overrides"
        )
        utils.load_prompt_config()
        return None
    except ValueError as e:
        utils.log(f"Error: {e}")
        return e
def handle_set_system_prompt_config(form):
    config_str = form.get('system_prompts', '')
    try:
        utils.save_config_to_file(
            config_str=config_str,
            file_path=utils.SYSTEM_PROMPTS_FILE,
            config_name="System prompts"
        )
        utils.load_system_prompt_config()
        return None
    except ValueError as e:
        utils.log(f"Error: {e}")
        return e
