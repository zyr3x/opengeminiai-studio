"""
Flask routes for optimization metrics and monitoring.
"""
from flask import Blueprint, jsonify
from app import optimization

metrics_bp = Blueprint('metrics', __name__)

@metrics_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """
    Returns optimization metrics including cache hit rate, tokens saved,
    connection pool stats, and rate limiter status.
    """
    metrics = optimization.get_metrics()
    
    # Добавляем информацию о ФАЗЕ 2
    phase2_metrics = {
        'connection_pool_active': optimization._http_session is not None,
        'rate_limiter_active': optimization._gemini_rate_limiter is not None,
        'thread_pool_active': optimization._tool_executor is not None,
        'cached_contexts_count': len(optimization._cached_contexts)
    }
    
    return jsonify({
        "status": "success",
        "phase": "2",
        "metrics": metrics,
        "phase2": phase2_metrics
    })

@metrics_bp.route('/metrics/reset', methods=['POST'])
def reset_metrics():
    """
    Resets optimization metrics.
    """
    optimization.reset_metrics()
    return jsonify({
        "status": "success",
        "message": "Metrics reset successfully"
    })

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
