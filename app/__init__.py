from flask import Flask
from .config import config

def create(app: Flask):
    """Application factory function to set up and configure the Flask app."""
    # Local imports for encapsulated setup
    import app.mcp_handler as mcp_handler
    import app.utils as utils

    # Import Blueprints
    from app.controllers.proxy import proxy_bp
    from app.controllers.settings import settings_bp
    from app.controllers.mcp_settings import mcp_settings_bp
    from app.controllers.prompt_settings import prompt_settings_bp
    from app.controllers.web_ui import web_ui_bp
    from app.controllers.web_ui_chat import web_ui_chat_bp
    from app.controllers.metrics import metrics_bp
    from app.db import init_db

    init_db()
    # Load configurations from external modules (MCP/Prompts)
    mcp_handler.load_mcp_config()
    utils.load_prompt_config()
    utils.load_system_prompt_config()

    # Register blueprints
    app.register_blueprint(proxy_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(mcp_settings_bp)
    app.register_blueprint(prompt_settings_bp)
    app.register_blueprint(web_ui_bp)
    app.register_blueprint(web_ui_chat_bp)
    app.register_blueprint(metrics_bp)

    return app

def run(app: Flask):
    app = create(app)
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT)