from quart import Blueprint, jsonify, request
import os
import asyncio

logs_bp = Blueprint('logs', __name__)

LOG_FILE = '/app/var/log/output.log'

def _read_logs_sync():
    if not os.path.exists(LOG_FILE):
        return None
    with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
        return f.readlines()

@logs_bp.route('/logs/data')
async def get_logs():
    query = request.args.get('search', '').lower()
    limit = int(request.args.get('limit', 2000))
    
    try:
        # Run file I/O in a separate thread to prevent blocking the async loop
        lines = await asyncio.to_thread(_read_logs_sync)
        
        if lines is None:
             return jsonify({"error": "Log file not found at " + LOG_FILE, "logs": []})
            
        if query:
            lines = [l for l in lines if query in l.lower()]
            
        subset = lines[-limit:]
        return jsonify({"logs": subset})
    except Exception as e:
        return jsonify({"error": str(e), "logs": []})