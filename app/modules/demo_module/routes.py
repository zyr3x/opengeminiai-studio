from flask import Blueprint, jsonify

demo_bp = Blueprint('demo_bp', __name__)

@demo_bp.route('/hello')
async def hello():
    return jsonify({"message": "Hello from asynchronously autoloaded module!"})
