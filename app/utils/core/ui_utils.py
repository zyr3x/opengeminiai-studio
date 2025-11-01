import json
import os
from datetime import datetime
from app.config import config
from app.utils.core import mcp_handler, tools as utils, logging
from app.utils.core.prompt_loader import load_default_system_prompts, load_default_override_prompts
from app.utils.core.metrics_utils import get_view_metrics
from app.utils.core.config_loader import load_json_file

def get_index_context():
    api_key_status = "Set" if config.API_KEY else "Not Set"
    current_mcp_config_str = ""
    if os.path.exists(mcp_handler.MCP_CONFIG_FILE):
        with open(mcp_handler.MCP_CONFIG_FILE, 'r') as f:
            current_mcp_config_str = f.read()

    current_prompt_overrides_str = ""
    if os.path.exists(utils.PROMPT_OVERRIDES_FILE):
        with open(utils.PROMPT_OVERRIDES_FILE, 'r') as f:
            current_prompt_overrides_str = f.read()

    current_system_prompts_str = ""
    if os.path.exists(utils.SYSTEM_PROMPTS_FILE):
        with open(utils.SYSTEM_PROMPTS_FILE, 'r') as f:
            current_system_prompts_str = f.read()

    default_prompt_overrides = load_default_override_prompts()
    prompt_profiles = default_prompt_overrides
    if current_prompt_overrides_str.strip():
        try:
            prompt_profiles = json.loads(current_prompt_overrides_str)
        except json.JSONDecodeError:
            pass

    default_system_prompts = load_default_system_prompts()
    system_prompt_profiles = default_system_prompts
    if current_system_prompts_str.strip():
        try:
            system_prompt_profiles = json.loads(current_system_prompts_str)
        except json.JSONDecodeError:
            pass

    current_agent_prompts_str = ""
    if os.path.exists(utils.AGENT_PROMPTS_FILE):
        with open(utils.AGENT_PROMPTS_FILE, 'r') as f:
            current_agent_prompts_str = f.read()

    from app.utils.core.prompt_loader import load_default_agent_prompts
    default_agent_prompts = load_default_agent_prompts()
    agent_prompt_profiles = default_agent_prompts
    if current_agent_prompts_str.strip():
        try:
            agent_prompt_profiles = json.loads(current_agent_prompts_str)
        except json.JSONDecodeError:
            pass

    default_mcp_config = load_json_file('etc/mcp/default.json')
    mcp_config_data = default_mcp_config
    if current_mcp_config_str.strip():
        try:
            loaded_mcp_config = json.loads(current_mcp_config_str)
            if "mcpServers" in loaded_mcp_config and isinstance(loaded_mcp_config.get("mcpServers"), dict):
                mcp_config_data = loaded_mcp_config
            mcp_config_data["disableAllTools"] = loaded_mcp_config.get("disableAllTools",
                                                                       mcp_handler.DISABLE_ALL_MCP_TOOLS_DEFAULT)
        except json.JSONDecodeError:
            pass

    mcp_functions_by_tool = {}
    for func_decl in mcp_handler.mcp_function_declarations:
        tool_name = mcp_handler.mcp_function_to_tool_map.get(func_decl['name'])
        if tool_name:
            if tool_name not in mcp_functions_by_tool:
                mcp_functions_by_tool[tool_name] = []
            mcp_functions_by_tool[tool_name].append(func_decl)

    return {
        'API_KEY': config.API_KEY, 'api_key_status': api_key_status,
        'current_mcp_config_str': current_mcp_config_str, 'mcp_config': mcp_config_data,
        'default_mcp_config_json': utils.pretty_json(default_mcp_config),
        'prompt_profiles': prompt_profiles, 'current_prompt_overrides_str': current_prompt_overrides_str,
        'default_prompt_overrides_json': utils.pretty_json(default_prompt_overrides),
        'system_prompt_profiles': system_prompt_profiles, 'current_system_prompts_str': current_system_prompts_str,
        'default_system_prompts_json': utils.pretty_json(default_system_prompts),
        'agent_prompt_profiles': agent_prompt_profiles, 'current_agent_prompts_str': current_agent_prompts_str,
        'default_agent_prompts_json': utils.pretty_json(default_agent_prompts),
        'verbose_logging_status': config.VERBOSE_LOGGING,
        'debug_client_logging_status': config.DEBUG_CLIENT_LOGGING,
        'streaming_enabled': config.STREAMING_ENABLED,
        'streaming_progress_enabled': config.STREAMING_PROGRESS_ENABLED,
        'selective_context_enabled': config.SELECTIVE_CONTEXT_ENABLED,
        'context_min_relevance_score': config.CONTEXT_MIN_RELEVANCE_SCORE,
        'context_always_keep_recent': config.CONTEXT_ALWAYS_KEEP_RECENT,
        'min_context_caching_tokens': config.MIN_CONTEXT_CACHING_TOKENS,
        'allowed_code_paths': ','.join(config.ALLOWED_CODE_PATHS) if config.ALLOWED_CODE_PATHS else '',
        'max_code_injection_size_kb': config.MAX_CODE_INJECTION_SIZE_KB,
        'agent_aux_model_enabled': config.AGENT_AUX_MODEL_ENABLED,
        'agent_aux_model_name': config.AGENT_AUX_MODEL_NAME,
        'current_max_function_declarations': mcp_config_data.get("maxFunctionDeclarations",
                                                                 mcp_handler.max_function_declarations_limit),
        'current_disable_all_mcp_tools': mcp_handler.disable_all_mcp_tools,
        'current_year': datetime.now().year,
        'mcp_functions_by_tool': mcp_functions_by_tool,
        'metrics': get_view_metrics()
    }
