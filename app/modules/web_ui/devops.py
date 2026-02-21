import os
import subprocess
import signal
import time
import fcntl
from flask import Blueprint, jsonify, Response, request
from app.config import config

devops_bp = Blueprint('devops', __name__)

# In-memory store for running processes
_running_processes = {}

@devops_bp.route('/api/devops/status', methods=['GET'])
def get_devops_status():
    status = {}
    for script_name, proc in list(_running_processes.items()):
        if proc.poll() is None:
            status[script_name] = {"status": "running", "pid": proc.pid}
        else:
            status[script_name] = {"status": "stopped", "exit_code": proc.returncode}
            del _running_processes[script_name]
    return jsonify(status)

@devops_bp.route('/api/devops/start', methods=['POST'])
def start_devops_script():
    data = request.json
    script_name = data.get('script_name')
    if not script_name:
        return jsonify({"error": "Script name is required"}), 400

    # Ensure it's a known safe script
    allowed_scripts = ['bugfix_loop.sh', 'coverage_loop.sh', 'log_monitor.sh']
    if script_name not in allowed_scripts:
        return jsonify({"error": f"Invalid script. Must be one of {allowed_scripts}"}), 400

    if script_name in _running_processes and _running_processes[script_name].poll() is None:
        return jsonify({"error": "Script is already running"}), 400

    script_path = os.path.join(config.PROJECT_ROOT, script_name)
    if not os.path.exists(script_path):
        return jsonify({"error": f"Script not found at {script_path}"}), 404

    try:
        # Start bash script. We use setsid so we can kill the entire process group
        proc = subprocess.Popen(
            ['bash', script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=config.PROJECT_ROOT,
            text=True,
            bufsize=1, # Line buffered
            preexec_fn=os.setsid
        )
        
        # Set stdout to non-blocking
        fd = proc.stdout.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        _running_processes[script_name] = proc
        return jsonify({"success": True, "pid": proc.pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@devops_bp.route('/api/devops/stop', methods=['POST'])
def stop_devops_script():
    data = request.json
    script_name = data.get('script_name')
    
    if script_name not in _running_processes:
         return jsonify({"success": True, "message": "Script is not running or tracking"})

    proc = _running_processes[script_name]
    if proc.poll() is not None:
         del _running_processes[script_name]
         return jsonify({"success": True, "message": "Script was already stopped"})

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception as e:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except:
             pass

    del _running_processes[script_name]
    return jsonify({"success": True})

@devops_bp.route('/api/devops/stream', methods=['GET'])
def stream_devops_logs():
    script_name = request.args.get('script_name')
    if script_name not in _running_processes:
        return jsonify({"error": "Script is not running"}), 404

    proc = _running_processes[script_name]

    def generate():
        try:
            while proc.poll() is None:
                try:
                    line = proc.stdout.readline()
                    if line:
                        # SSE format
                        import json
                        yield f"data: {json.dumps({'log': line})}\n\n"
                    else:
                        time.sleep(0.1)
                except IOError:
                    # Non-blocking read might throw IOError right away if no info
                    time.sleep(0.1)
            
            # Read remaining logs after process exits
            try:
                for line in proc.stdout.readlines():
                    if line:
                        import json
                        yield f"data: {json.dumps({'log': line})}\n\n"
            except IOError:
                pass
            
            import json
            yield f"event: end\ndata: {json.dumps({'exit_code': proc.returncode})}\n\n"
        except GeneratorExit:
            pass # Client disconnected

    return Response(generate(), mimetype='text/event-stream')
