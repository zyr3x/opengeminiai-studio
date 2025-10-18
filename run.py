"""
Entry point for the OpenGeminiAI Studio Flask application.

This script initializes the Flask app using the application factory
and runs it. It's intended to be executed directly.
"""
from flask import Flask
from app import run
from app.mcp_handler import load_mcp_config
from app.utils import load_prompt_config, load_system_prompt_config
from app.db import init_db

if __name__ == '__main__':
    app = run(Flask(__name__))
    init_db()  # Ensure database is initialized on startup
    load_mcp_config()
    load_prompt_config()
    load_system_prompt_config()

