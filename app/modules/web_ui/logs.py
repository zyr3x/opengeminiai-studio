from flask import Blueprint, jsonify, request
import os

logs_bp = Blueprint('logs', __name__)

LOG_FILE = '/app/var/log/output.log'

@logs_bp.route('/logs/data')
def get_logs():
    query = request.args.get('search', '').lower()
    limit = int(request.args.get('limit', 2000))
    
    if not os.path.exists(LOG_FILE):
        return jsonify({"error": "Log file not found at " + LOG_FILE, "logs": []})
        
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            
        if query:
            lines = [l for l in lines if query in l.lower()]
            
        # Return last N lines
        subset = lines[-limit:]
        return jsonify({"logs": subset})
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})