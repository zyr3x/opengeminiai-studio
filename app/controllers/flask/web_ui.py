from flask import Blueprint, Response, render_template
from app.utils.core.ui_utils import get_index_context
from app.config import config

web_ui_bp = Blueprint('web_ui', __name__)

@web_ui_bp.route('/', methods=['GET'])
def index():
    context = get_index_context()
    return render_template('index.html', **context)

@web_ui_bp.route('/favicon.ico')
def favicon():
    return Response(config.FAVICON, mimetype='image/svg+xml')
