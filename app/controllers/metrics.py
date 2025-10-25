"""
Flask routes for optimization metrics and monitoring.
Compatible with both Flask and Quart.
"""
try:
    # Try Quart first (async mode)
    from quart import Blueprint, jsonify, flash, redirect, url_for
except ImportError:
    # Fallback to Flask (sync mode)
    from flask import Blueprint, jsonify, flash, redirect, url_for

from app import optimization

metrics_bp = Blueprint('metrics', __name__)

@metrics_bp.route('/metrics', methods=['GET'])
def get_metrics():
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
        from app import context_selector
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

    return jsonify({
        "status": "success",
        "phase": "3",
        "metrics": metrics,
        "phase2": phase2_metrics,
        "phase3": phase3_metrics
    })

@metrics_bp.route('/metrics/reset', methods=['POST'])
def reset_metrics():
    """
    Resets optimization metrics.
    """
    optimization.reset_metrics()
    flash("Optimization metrics have been successfully reset.", "success")
    return redirect(url_for('metrics.get_metrics'))

@metrics_bp.route('/metrics/api', methods=['GET'])
def get_metrics_api():
    """
    Returns optimization metrics as JSON for AJAX updates.
    """
    metrics_data = optimization.get_metrics()
    token_stats = optimization.get_key_token_stats()

    metrics_data['key_token_stats'] = token_stats
    return jsonify(metrics_data)

@metrics_bp.route('/metrics/cleanup', methods=['POST'])
def cleanup_resources():
    """
    Manually triggers cleanup of expired resources (cached contexts, etc.)
    """
    optimization.clear_expired_contexts()
    return jsonify({
        "status": "success",
        "message": "Expired resources cleaned up"
    })
