import os
from app.config import config
from app.utils.core.config_loader import load_json_file


def load_default_system_prompts():
    system_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "system", "default.json")
    return load_json_file(system_prompts_file_path, default={})
def load_default_override_prompts():
    override_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "override", "default.json")
    return load_json_file(override_prompts_file_path, default={})
def load_default_agent_prompts():
    agent_prompts_file_path = os.path.join(config.ETC_DIR, "prompt", "agent", "default.json")
    return load_json_file(agent_prompts_file_path, default={})

