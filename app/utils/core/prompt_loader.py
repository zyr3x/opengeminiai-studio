import os
from app.config import config
from app.utils.core.config_loader import load_json_file


def load_default_system_prompts():
    """
    Loads default system prompts from the default.json file located in etc/prompt/system.
    Returns an empty dictionary if the file is not found, cannot be read, or is malformed JSON.
    """
    system_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "system", "default.json")
    return load_json_file(system_prompts_file_path, default={})


def load_default_override_prompts():
    """
    Loads default override prompts from the default.json file located in etc/prompt/override.
    Returns an empty dictionary if the file is not found, cannot be read, or is malformed JSON.
    """
    override_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "override", "default.json")
    return load_json_file(override_prompts_file_path, default={})

