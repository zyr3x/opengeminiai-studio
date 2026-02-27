from flask import Blueprint, jsonify, request
import os
import asyncio

logs_bp = Blueprint('logs', __name__)

LOG_FILE = '/app/var/log/output.log'

@logs_bp.route('/logs/data')
async def get_logs():
    query = request.args.get('search', '').lower()
    limit = int(request.args.get('limit', 2000))
    
    # Try multiple possible log locations
    possible_paths = [
        LOG_FILE,
        'var/log/output.log',
        'output.log'
    ]
    
    log_path = None
    for p in possible_paths:
        if os.path.exists(p):
            log_path = p
            break
            
    if not log_path:
        return jsonify({"error": "Log file not found", "logs": []})
        
    try:
        def read_tail():
            from collections import deque
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                # Use deque to efficiently get the last N lines
                if query:
                    return [line for line in f if query in line.lower()][-limit:]
                return list(deque(f, limit))

        subset = await asyncio.to_thread(read_tail)
        return jsonify({"logs": subset})
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})