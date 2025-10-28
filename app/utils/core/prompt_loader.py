import os
import json
from app.config import config

def load_default_system_prompts():
    """
    Loads default system prompts from the default.json file located in etc/prompt/system.
    Returns an empty dictionary if the file is not found, cannot be read, or is malformed JSON.
    """
    system_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "system", "default.json")
    if os.path.exists(system_prompts_file_path):
        try:
            with open(system_prompts_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Could not load default system prompts from {system_prompts_file_path}. "
                  f"JSON malformed. Returning empty defaults.")
        except IOError as e:
            print(f"Warning: Could not read default system prompts from {system_prompts_file_path}. "
                  f"Error: {e}. Returning empty defaults.")
    else:
        print(f"Info: Default system prompts file not found at {system_prompts_file_path}. Returning empty defaults.")
    return {}


def load_default_override_prompts():
    """
    Loads default override prompts from the default.json file located in etc/prompt/system.
    Returns an empty dictionary if the file is not found, cannot be read, or is malformed JSON.
    """
    system_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "override", "default.json")
    if os.path.exists(system_prompts_file_path):
        try:
            with open(system_prompts_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Could not load default override prompts from {system_prompts_file_path}. "
                  f"JSON malformed. Returning empty defaults.")
        except IOError as e:
            print(f"Warning: Could not read default override prompts from {system_prompts_file_path}. "
                  f"Error: {e}. Returning empty defaults.")
    else:
        print(f"Info: Default override prompts file not found at {system_prompts_file_path}. Returning empty defaults.")
    return {}

