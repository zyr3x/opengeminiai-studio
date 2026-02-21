import pytest
from unittest.mock import patch, MagicMock

@patch('app.utils.core.optimization.get_metrics')
@patch('app.utils.core.optimization._http_session', new_callable=MagicMock)
@patch('app.utils.core.optimization._gemini_rate_limiter', new_callable=MagicMock)
@patch('app.utils.core.optimization._tool_executor', new_callable=MagicMock)
@patch('app.utils.core.optimization._cached_contexts', [])
@patch('app.utils.core.context_selector.get_selective_context_stats')
@patch('app.config.config')
def test_get_view_metrics_success(mock_config, mock_stats, mock_executor, mock_limiter, mock_session, mock_get_metrics):
    from app.utils.core.metrics_utils import get_view_metrics
    
    mock_get_metrics.return_value = {"metric": 1}
    mock_stats.return_value = {"stat": 2}
    mock_config.SELECTIVE_CONTEXT_ENABLED = True
    mock_config.CONTEXT_MIN_RELEVANCE_SCORE = 0.5
    mock_config.CONTEXT_ALWAYS_KEEP_RECENT = 10
    
    res = get_view_metrics()
    
    assert res['status'] == 'success'
    assert res['phase'] == '3'
    assert res['metrics'] == {"metric": 1}
    assert res['phase2']['connection_pool_active'] == True
    assert res['phase2']['rate_limiter_active'] == True
    assert res['phase2']['thread_pool_active'] == True
    assert res['phase2']['cached_contexts_count'] == 0
    assert res['phase3']['selective_context_enabled'] == True
    assert res['phase3']['min_relevance_score'] == 0.5
    assert res['phase3']['always_keep_recent'] == 10
    assert res['phase3']['stats'] == {"stat": 2}

@patch('app.utils.core.optimization.get_metrics')
@patch('app.utils.core.optimization._http_session', None)
@patch('app.utils.core.optimization._gemini_rate_limiter', None)
@patch('app.utils.core.optimization._tool_executor', None)
@patch('app.utils.core.optimization._cached_contexts', [])
@patch('app.utils.core.context_selector.get_selective_context_stats', side_effect=Exception("Mocked Error"))
def test_get_view_metrics_exception(mock_stats, mock_get_metrics):
    from app.utils.core.metrics_utils import get_view_metrics
    
    mock_get_metrics.return_value = {}
    
    res = get_view_metrics()
        
    assert res['status'] == 'success'
    assert res['phase2']['connection_pool_active'] == False
    assert res['phase3']['selective_context_enabled'] == False
    assert 'error' in res['phase3']
    assert 'Mocked Error' in res['phase3']['error']

