import pytest
from unittest.mock import patch

@patch('builtins.print')
@patch('app.utils.core.logging.config')
def test_log(mock_config, mock_print):
    from app.utils.core.logging import log
    
    mock_config.VERBOSE_LOGGING = True
    log("Test message")
    mock_print.assert_called_with("Test message")
    
    mock_print.reset_mock()
    mock_config.VERBOSE_LOGGING = False
    log("Hidden message")
    mock_print.assert_not_called()

@patch('builtins.print')
@patch('app.utils.core.logging.config')
def test_debug(mock_config, mock_print):
    from app.utils.core.logging import debug
    
    mock_config.DEBUG_CLIENT_LOGGING = True
    debug("Debug message")
    mock_print.assert_called_with("Debug message")
    
    mock_print.reset_mock()
    mock_config.DEBUG_CLIENT_LOGGING = False
    debug("Hidden debug")
    mock_print.assert_not_called()

@patch('app.utils.core.logging.log')
@patch('app.utils.core.logging.config')
def test_set_verbose_logging(mock_config, mock_log):
    from app.utils.core.logging import set_verbose_logging
    
    set_verbose_logging(True)
    mock_config.set_param.assert_called_with('VERBOSE_LOGGING', True)
    mock_log.assert_called_with("Verbose logging has been enabled.")
    
    mock_config.set_param.reset_mock()
    mock_log.reset_mock()
    
    set_verbose_logging(False)
    mock_config.set_param.assert_called_with('VERBOSE_LOGGING', False)
    mock_log.assert_called_with("Verbose logging has been disabled.")

@patch('app.utils.core.logging.log')
@patch('app.utils.core.logging.config')
def test_set_debug_client_logging(mock_config, mock_log):
    from app.utils.core.logging import set_debug_client_logging
    
    set_debug_client_logging(True)
    mock_config.set_param.assert_called_with('DEBUG_CLIENT_LOGGING', True)
    mock_log.assert_called_with("Debug client logging has been enabled.")
    
    mock_config.set_param.reset_mock()
    mock_log.reset_mock()
    
    set_debug_client_logging(False)
    mock_config.set_param.assert_called_with('DEBUG_CLIENT_LOGGING', False)
    mock_log.assert_called_with("Debug client logging has been disabled.")
