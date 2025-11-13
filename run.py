"""
Entry point for the OpenGeminiAI Studio Flask application.

This script initializes the Flask app using the application factory
and runs it. It's intended to be executed directly.
"""
import asyncio
from app import run
from app import config

if __name__ == '__main__':
    try:
        if config.ASYNC_MODE:
            asyncio.run(run(__name__))
        else:
            run(__name__)
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
