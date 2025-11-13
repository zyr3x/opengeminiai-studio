from quart import Blueprint, Response, render_template
from app.utils.core.ui_utils import get_index_context
from app.config import config

web_ui_bp = Blueprint('web_ui', __name__)

@web_ui_bp.route('/', methods=['GET'])
async def index():
    context = get_index_context()
    return await render_template('index.html', **context)

@web_ui_bp.route('/favicon.ico')
async def favicon():
    return Response(config.FAVICON, mimetype='image/svg+xml')
