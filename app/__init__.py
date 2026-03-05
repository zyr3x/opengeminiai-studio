import os
import asyncio
from pathlib import Path
from flask import Flask
from .core.config import settings
from .core.mcp_server import mcp
from .autoloader import Autoloader

def create_app():
    """Application factory for the OpenGeminiAI Studio unified architecture."""
    template_dir = Path(__file__).parent.parent / 'templates'
    static_dir = Path(__file__).parent.parent / 'static'
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = settings.SECRET_KEY
    
    # Initialize the automated JSON module loader
    print("\n--- Initializing Modules ---")
    from .utils.core import mcp_handler
    mcp_handler.load_mcp_config()
    autoloader = Autoloader(app=app, mcp_server=mcp)
    autoloader.load_all()
    print("----------------------------\n")
    
    @app.route('/ping')
    async def ping():
        """Basic health check endpoint."""
        return {"status": "ok", "mode": "async flask 3.x unified architecture"}

    return app

async def run_asgi(app: Flask):
    """
    Run the Flask app along with the FastMCP server via Hypercorn.
    We convert the sync/async Flask WSGI app to an ASGI app using asgiref.
    """
    from hypercorn.asyncio import serve
    from hypercorn.config import Config as HypercornConfig
    from asgiref.wsgi import WsgiToAsgi
    
    # Convert Flask WSGI to ASGI
    asgi_flask_app = WsgiToAsgi(app)
    
    # FastMCP provides an ASGI app via get_asgi_app() or similar in newer versions, 
    # but the easiest way to serve both is to just run the Flask app for now,
    # as mcp tools are just registered. If we need to expose the MCP server 
    # externally via SSE, we can mount it here later.
    print(f"🚀 FastMCP Server '{mcp.name}' initialized.")
    async def _print_tools():
        tools = await mcp.list_tools()
        print(f"🚀 FastMCP registered tools at boot: {[t.name for t in tools]}")
    asyncio.create_task(_print_tools())
    
    hypercorn_config = HypercornConfig()
    hypercorn_config.bind = [f"{settings.SERVER_HOST}:{settings.SERVER_PORT}"]
    hypercorn_config.accesslog = "-"
    hypercorn_config.errorlog = "-"
    
    print(f"🚀 Starting Unified OpenGeminiAI Studio on http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
    
    # Serve the wrapped ASGI Flask app asynchronously
    await serve(asgi_flask_app, hypercorn_config)

def run():
    """Main start function."""
    app = create_app()
    asyncio.run(run_asgi(app))