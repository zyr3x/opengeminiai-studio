import os
from unittest.mock import patch

def test_load_default_system_prompts():
    with patch('app.utils.core.prompt_loader.config') as mock_config, \
         patch('app.utils.core.prompt_loader.load_json_file') as mock_load_json:
        
        mock_config.ETC_DIR = "/mock/etc"
        mock_load_json.return_value = {"a": 1}
        
        from app.utils.core.prompt_loader import load_default_system_prompts
        res = load_default_system_prompts()
        
        assert res == {"a": 1}
        expected_path = os.path.join("/mock/etc", "prompt", "system", "default.json")
        mock_load_json.assert_called_with(expected_path, default={})

def test_load_default_override_prompts():
    with patch('app.utils.core.prompt_loader.config') as mock_config, \
         patch('app.utils.core.prompt_loader.load_json_file') as mock_load_json:
        
        mock_config.ETC_DIR = "/mock/etc"
        mock_load_json.return_value = {"b": 2}
        
        from app.utils.core.prompt_loader import load_default_override_prompts
        res = load_default_override_prompts()
        
        assert res == {"b": 2}
        expected_path = os.path.join("/mock/etc", "prompt", "override", "default.json")
        mock_load_json.assert_called_with(expected_path, default={})

def test_load_default_agent_prompts():
    with patch('app.utils.core.prompt_loader.config') as mock_config, \
         patch('app.utils.core.prompt_loader.load_json_file') as mock_load_json:
        
        mock_config.ETC_DIR = "/mock/etc"
        mock_load_json.return_value = {"c": 3}
        
        from app.utils.core.prompt_loader import load_default_agent_prompts
        res = load_default_agent_prompts()
        
        assert res == {"c": 3}
        expected_path = os.path.join("/mock/etc", "prompt", "agent", "default.json")
        mock_load_json.assert_called_with(expected_path, default={})
