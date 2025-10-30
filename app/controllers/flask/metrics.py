"""
Flask routes for optimization metrics and monitoring.
"""
from flask import Blueprint, jsonify, flash, redirect, url_for

from app.utils.core import optimization
from app.utils.core.metrics_utils import get_view_metrics

metrics_bp = Blueprint('metrics', __name__)

@metrics_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """
    Returns optimization metrics including cache hit rate, tokens saved,
    connection pool stats, rate limiter status, and selective context stats.
    """
    return jsonify(get_view_metrics())

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
