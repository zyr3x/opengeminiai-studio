"""
Async entry point for the OpenGeminiAI Studio using Quart.

This version uses async/await for improved performance and concurrency.
To use: python run_async.py
"""
import asyncio
import os
from quart import Quart
from app.config import config
from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

async def create_async_app():
    """Creates and configures the async Quart application."""
    app = Quart(__name__)
    
    # Set secret key for sessions (required by Quart)
    app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())
    
    # Import async utilities
    import app.async_utils as async_utils
    import app.mcp_handler as mcp_handler
    import app.utils as utils
    
    # Import Blueprints - mix of async and sync
    from app.controllers.async_proxy import async_proxy_bp
    from app.controllers.settings import settings_bp
    from app.controllers.mcp_settings import mcp_settings_bp
    from app.controllers.prompt_settings import prompt_settings_bp
    from app.controllers.web_ui import web_ui_bp
    from app.controllers.web_ui_chat import web_ui_chat_bp
    from app.controllers.metrics import metrics_bp
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

async def main():
    """Main async entry point."""
    app = await create_async_app()
    
    # Configure Hypercorn
    hypercorn_config = HypercornConfig()
    hypercorn_config.bind = [f"{config.SERVER_HOST}:{config.SERVER_PORT}"]
    hypercorn_config.accesslog = "-"  # Log to stdout
    hypercorn_config.errorlog = "-"   # Log to stderr
    
    # Run with Hypercorn (async ASGI server)
    await serve(app, hypercorn_config)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
