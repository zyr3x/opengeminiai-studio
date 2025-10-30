from app.utils.core import optimization

def get_view_metrics():
    """
    Returns optimization metrics including cache hit rate, tokens saved,
    connection pool stats, rate limiter status, and selective context stats.
    """
    metrics = optimization.get_metrics()

    # Add information about PHASE 2
    phase2_metrics = {
        'connection_pool_active': optimization._http_session is not None,
        'rate_limiter_active': optimization._gemini_rate_limiter is not None,
        'thread_pool_active': optimization._tool_executor is not None,
        'cached_contexts_count': len(optimization._cached_contexts)
    }

    # Add information about PHASE 3
    try:
        from app.utils.core import context_selector
        from app.config import config as app_config

        phase3_metrics = {
            'selective_context_enabled': app_config.SELECTIVE_CONTEXT_ENABLED,
            'min_relevance_score': app_config.CONTEXT_MIN_RELEVANCE_SCORE,
            'always_keep_recent': app_config.CONTEXT_ALWAYS_KEEP_RECENT,
            'stats': context_selector.get_selective_context_stats()
        }
    except Exception as e:
        phase3_metrics = {
            'selective_context_enabled': False,
            'error': f'Module not loaded: {str(e)}'
        }

    return {
        "status": "success",
        "phase": "3",
        "metrics": metrics,
        "phase2": phase2_metrics,
        "phase3": phase3_metrics
    }
