from flask import Flask
from .config import config
import os
from quart import Quart
from app.config import config
from hypercorn.asyncio import serve
from pathlib import Path
from hypercorn.config import Config as HypercornConfig

def create_flask_app(app: Flask):
    """Application factory function to set up and configure the Flask app."""
    # Local imports for encapsulated setup
    import app.utils.flask.mcp_handler as mcp_handler
    import app.utils.core.tools as utils

    # Import Blueprints
    from app.controllers.flask.proxy import proxy_bp
    from app.controllers.flask.settings import settings_bp
    from app.controllers.flask.mcp_settings import mcp_settings_bp
    from app.controllers.flask.prompt_settings import prompt_settings_bp
    from app.controllers.flask.web_ui import web_ui_bp
    from app.controllers.flask.web_ui_chat import web_ui_chat_bp
    from app.controllers.flask.metrics import metrics_bp
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

def run_flask_app(app: Flask):
    app = create_flask_app(app)
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT)

async def create_quart_app(app: Quart):
    """Creates and configures the async Quart application."""
    # Set secret key for sessions (required by Quart)
    # Generate a persistent key if not set in environment
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key or secret_key == 'your-secret-key-here' or secret_key == 'your-secret-key-here-change-this-to-random-string':
        import secrets
        secret_key = secrets.token_hex(32)
        print(f"⚠️  Warning: Using generated SECRET_KEY. Set SECRET_KEY in .env for persistent sessions.")
    app.secret_key = secret_key

    # Import async utilities
    import app.utils.quart.utils as async_utils
    import app.utils.flask.mcp_handler as mcp_handler
    import app.utils.core.tools as utils

    # Import Blueprints - mix of async and sync
    from app.controllers.quart.proxy import async_proxy_bp
    from app.controllers.quart.settings import settings_bp
    from app.controllers.quart.mcp_settings import mcp_settings_bp
    from app.controllers.quart.prompt_settings import prompt_settings_bp
    from app.controllers.quart.web_ui import web_ui_bp
    from app.controllers.quart.web_ui_chat import web_ui_chat_bp
    from app.controllers.quart.metrics import metrics_bp
    from app.db import init_db

    # Initialize database
    init_db()

    # Load configurations
    mcp_handler.load_mcp_config()
    utils.load_prompt_config()
    utils.load_system_prompt_config()

    # Register blueprints
    app.register_blueprint(async_proxy_bp)  # Async proxy
    app.register_blueprint(settings_bp)
    app.register_blueprint(mcp_settings_bp)
    app.register_blueprint(prompt_settings_bp)
    app.register_blueprint(web_ui_bp)
    app.register_blueprint(web_ui_chat_bp)
    app.register_blueprint(metrics_bp)

    # Setup cleanup on shutdown
    @app.before_serving
    async def startup():
        print("🚀 Starting OpenGeminiAI Studio (Async Mode)")
        print(f"   Server: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
        print(f"   API: http://{config.SERVER_HOST}:{config.SERVER_PORT}/v1")

    @app.after_serving
    async def shutdown():
        print("\n🛑 Shutting down...")
        # Close async session
        await async_utils.close_async_session()
        print("✓ Cleanup complete")

    return app

async def run_quart_app(app: Quart):
    """Main async entry point."""
    app = await create_quart_app(app)

    # Configure Hypercorn
    hypercorn_config = HypercornConfig()
    hypercorn_config.bind = [f"{config.SERVER_HOST}:{config.SERVER_PORT}"]
    hypercorn_config.accesslog = "-"  # Log to stdout
    hypercorn_config.errorlog = "-"  # Log to stderr

    # Run with Hypercorn (async ASGI server)
    await serve(app, hypercorn_config)

if config.ASYNC_MODE:
    async def run(name):
        template_dir = Path(__file__).parent.parent / 'templates'
        static_dir = Path(__file__).parent.parent / 'static'
        return await run_quart_app(Quart(__name__, template_folder=template_dir, static_folder=static_dir))
else:
    def run(name):
       return run_flask_app(Flask(name))
