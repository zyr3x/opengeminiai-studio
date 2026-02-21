import os
import pytest
from unittest.mock import patch, mock_open, MagicMock

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {
        "UPSTREAM_URL": "http://example.com",
        "API_KEY": "test_key",
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": "9090",
        "ASYNC_MODE": "false",
        "SELECTIVE_CONTEXT_ENABLED": "false",
        "ALLOWED_CODE_PATHS": "/path/1, /path/2",
        "ALLOWED_MODELS": "model1, model2",
        "IGNORED_MODELS": "model3, model4",
    }, clear=True):
        yield

@patch('app.config.api_key_manager')
@patch('app.config.ai_provider_manager')
@patch('builtins.open', new_callable=mock_open, read_data="<svg></svg>")
@patch('app.config.load_dotenv')
def test_app_config_init(mock_dotenv, mock_file, mock_ai_provider_manager, mock_api_key_manager, mock_env):
    mock_api_key_manager.get_active_key_value.return_value = "mocked_key"
    mock_ai_provider_manager.get_active_provider.return_value = {
        'base_url': 'http://mock.ai',
        'api_key': 'mock_ai_key',
        'model': 'mock_model'
    }
    
    from app.config import AppConfig
    
    config = AppConfig()
    
    assert config.API_KEY == "mocked_key"
    assert config.UPSTREAM_URL == "http://example.com"
    assert config.SERVER_HOST == "127.0.0.1"
    assert config.SERVER_PORT == 9090
    assert config.ASYNC_MODE is False
    assert config.SELECTIVE_CONTEXT_ENABLED is False
    assert len(config.ALLOWED_CODE_PATHS) == 2
    assert config.ALLOWED_MODELS == ['model1', 'model2']
    assert config.IGNORED_MODELS == ['model3', 'model4']
    assert config.FAVICON == "<svg></svg>"
    
    assert config.OPENAI_BASE_URL == 'http://mock.ai'
    assert config.OPENAI_API_KEY == 'mock_ai_key'
    assert config.OPENAI_MODEL_NAME == 'mock_model'

@patch('app.config.api_key_manager')
@patch('app.config.ai_provider_manager')
@patch('builtins.open', new_callable=mock_open, read_data="<svg></svg>")
@patch('app.config.load_dotenv')
def test_app_config_missing_upstream(mock_dotenv, mock_file, mock_ai_provider_manager, mock_api_key_manager):
    with patch.dict(os.environ, clear=True):
        from app.config import AppConfig
        with pytest.raises(ValueError, match="UPSTREAM_URL environment variable not set"):
            AppConfig()

@patch('app.config.api_key_manager')
@patch('app.config.ai_provider_manager')
@patch('builtins.open', new_callable=mock_open, read_data="<svg></svg>")
@patch('app.config.load_dotenv')
@patch('app.config.set_key')
def test_app_config_methods(mock_set_key, mock_dotenv, mock_file, mock_ai_provider_manager, mock_api_key_manager, mock_env):
    mock_api_key_manager.get_active_key_value.return_value = "mocked_key"
    from app.config import AppConfig
    config = AppConfig()
    
    # Test set_param
    config.set_param("TEST_PARAM", "test_value")
    assert config.TEST_PARAM == "test_value"
    mock_set_key.assert_called_with('.env', 'TEST_PARAM', 'test_value')
    
    # Test get_param
    assert config.get_param("TEST_PARAM") == "test_value"
    assert config.get_param("NON_EXISTENT") is None
    
    # Test reload_api_key
    mock_api_key_manager.get_active_key_value.return_value = "new_mocked_key"
    config.reload_api_key()
    assert config.API_KEY == "new_mocked_key"
    
    # Test set_api_key
    config.set_api_key("manual_key")
    assert config.API_KEY == "manual_key"
    mock_set_key.assert_called_with('.env', 'API_KEY', 'manual_key')
