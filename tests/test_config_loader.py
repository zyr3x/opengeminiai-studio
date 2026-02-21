import os
import tempfile
import json
import pytest
from unittest.mock import patch

@patch('app.utils.core.config_loader.log')
def test_resolve_path_exists(mock_log):
    from app.utils.core.config_loader import _resolve_path
    
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf_name = tf.name
    
    try:
        assert _resolve_path(tf_name) == tf_name
    finally:
        os.remove(tf_name)

@patch('app.utils.core.config_loader.log')
def test_resolve_path_not_exists(mock_log):
    from app.utils.core.config_loader import _resolve_path
    assert _resolve_path("/path/does/not/exist/999999") is None

@patch('app.utils.core.config_loader.log')
def test_load_json_file_success(mock_log):
    from app.utils.core.config_loader import load_json_file
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
        tf.write('{"key": "value"}')
        tf_name = tf.name
        
    try:
        res = load_json_file(tf_name)
        assert res == {"key": "value"}
    finally:
        os.remove(tf_name)

@patch('app.utils.core.config_loader.log')
def test_load_json_file_with_bom(mock_log):
    from app.utils.core.config_loader import load_json_file
    
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tf:
        tf.write('\ufeff{"key": "value2"}')
        tf_name = tf.name
        
    try:
        res = load_json_file(tf_name)
        assert res == {"key": "value2"}
    finally:
        os.remove(tf_name)

@patch('app.utils.core.config_loader.log')
def test_load_json_file_invalid(mock_log):
    from app.utils.core.config_loader import load_json_file
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
        tf.write('{invalid json}')
        tf_name = tf.name
        
    try:
        res = load_json_file(tf_name, default={"def": 1})
        assert res == {"def": 1}
        mock_log.assert_called()
    finally:
        os.remove(tf_name)

@patch('app.utils.core.config_loader.log')
def test_load_text_file_lines(mock_log):
    from app.utils.core.config_loader import load_text_file_lines
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
        tf.write("line1\n# comment\n\nline2\n")
        tf_name = tf.name
        
    try:
        res = load_text_file_lines(tf_name)
        assert res == ["line1", "line2"]
    finally:
        os.remove(tf_name)

@patch('app.utils.core.config_loader.log')
def test_load_text_file_lines_not_found(mock_log):
    from app.utils.core.config_loader import load_text_file_lines
    res = load_text_file_lines("/path/not/exist", default=["def"])
    assert res == ["def"]
    mock_log.assert_called()
