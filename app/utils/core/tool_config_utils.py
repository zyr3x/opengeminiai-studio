from app.utils.core import tools as utils, logging

def get_prompt_override_config(full_prompt_text: str) -> dict:
    active_overrides = {}
    disable_mcp_tools_by_profile = True
    enable_native_tools_by_profile = False
    profile_selected_mcp_tools = []

    if utils.prompt_overrides and full_prompt_text:
        for profile_name, profile_data in utils.prompt_overrides.items():
            if isinstance(profile_data, dict):
                for trigger in profile_data.get('triggers', []):
                    if trigger in full_prompt_text:
                        active_overrides = profile_data.get('overrides', {})

                        if profile_data.get('disable_tools', False):
                            logging.log(f"MCP Tools Disabled by prompt override profile '{profile_name}'.")
                            disable_mcp_tools_by_profile = True
                        else:
                            disable_mcp_tools_by_profile = False
                            if profile_data.get('selected_mcp_tools'):
                                logging.log(f"MCP Tools explicitly selected by prompt override profile '{profile_name}': {profile_data['selected_mcp_tools']}")
                                profile_selected_mcp_tools = profile_data['selected_mcp_tools']

                        if profile_data.get('enable_native_tools', False):
                            logging.log(f"Native Google Tools Enabled by prompt override profile '{profile_name}'.")
                            enable_native_tools_by_profile = True

                        logging.log(f"Prompt override profile matched: '{profile_name}'")
                        return {
                            'active_overrides': active_overrides,
                            'disable_mcp_tools_by_profile': disable_mcp_tools_by_profile,
                            'enable_native_tools_by_profile': enable_native_tools_by_profile,
                            'profile_selected_mcp_tools': profile_selected_mcp_tools
                        }

    return {
        'active_overrides': active_overrides,
        'disable_mcp_tools_by_profile': True,
        'enable_native_tools_by_profile': False,
        'profile_selected_mcp_tools': []
    }
