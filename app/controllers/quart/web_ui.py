"""
Quart routes for the web UI, including the main page and direct chat API.
"""
from quart import Blueprint, Response, render_template
from app.utils.core.ui_utils import get_index_context

web_ui_bp = Blueprint('web_ui', __name__)

@web_ui_bp.route('/', methods=['GET'])
async def index():
    """
    Serves the main documentation and configuration page.
    Compatible with both Flask and Quart (async).
    """
    context = get_index_context()
    return await render_template('index.html', **context)

@web_ui_bp.route('/favicon.ico')
async def favicon():
    """Serves the favicon for the web interface."""
    favicon_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⚙️</text></svg>'
    return Response(favicon_svg, mimetype='image/svg+xml')
