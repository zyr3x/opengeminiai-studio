import os
import tempfile
import pytest
from unittest.mock import patch

def test_stream_file_content_success():
    from app.utils.core.streaming import stream_file_content
    
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tf:
        tf.write("abcdefghij" * 1000)
        tf_name = tf.name
        
    try:
        with patch('app.utils.core.streaming.STREAM_CHUNK_SIZE', 10):
            res = list(stream_file_content(tf_name))
            assert len(res) == 1000
            assert res[0] == "abcdefghij"
    finally:
        os.remove(tf_name)

@patch('app.utils.core.streaming.log')
def test_stream_file_content_error(mock_log):
    from app.utils.core.streaming import stream_file_content
    
    res = list(stream_file_content("/invalid/path/that/does/not/exist"))
    
    assert len(res) == 1
    assert "STREAMING ERROR" in res[0]
    mock_log.assert_called()

def test_stream_string():
    from app.utils.core.streaming import stream_string
    
    assert list(stream_string("", 5)) == []
    assert list(stream_string("abcde12345", 5)) == ["abcde", "12345"]
    assert list(stream_string("abc", 5)) == ["abc"]
