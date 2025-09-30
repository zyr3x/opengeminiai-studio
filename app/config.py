"""
Global configuration for Gemini-Proxy.
"""
import os
from dotenv import load_dotenv, set_key

# Load environment variables from .env file at startup
load_dotenv()

class AppConfig:
    """A class to hold application configuration."""
    def __init__(self):
        self.API_KEY = os.getenv("API_KEY")
        self.UPSTREAM_URL = os.getenv("UPSTREAM_URL")
        self.SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
        self.SERVER_PORT = int(os.getenv("SERVER_PORT", 8080))
        if not self.UPSTREAM_URL:
            raise ValueError("UPSTREAM_URL environment variable not set")

    def set_api_key(self, new_key: str):
        """Updates the API key in memory and in the .env file."""
        self.API_KEY = new_key
        set_key('.env', 'API_KEY', new_key)

# Singleton instance of the config
config = AppConfig()
