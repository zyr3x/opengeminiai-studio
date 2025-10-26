"""
Global configuration for Gemini-Proxy.
"""
import os
from dotenv import load_dotenv, set_key
from app.utils.core.api_key_manager import api_key_manager

# Load environment variables from .env file at startup
load_dotenv()

class AppConfig:
    """A class to hold application configuration."""
    def __init__(self):
        self.API_KEY = api_key_manager.get_active_key_value() or os.getenv("API_KEY", "")
        self.UPSTREAM_URL = os.getenv("UPSTREAM_URL")
        self.SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
        self.SERVER_PORT = int(os.getenv("SERVER_PORT", 8080))
        self.ASYNC_MODE = os.getenv("ASYNC_MODE", "true").lower() == "true"
        if not self.UPSTREAM_URL:
            raise ValueError("UPSTREAM_URL environment variable not set")
        
        self.SELECTIVE_CONTEXT_ENABLED = os.getenv("SELECTIVE_CONTEXT_ENABLED", "true").lower() == "true"
        self.CONTEXT_MIN_RELEVANCE_SCORE = float(os.getenv("CONTEXT_MIN_RELEVANCE_SCORE", "0.3"))
        self.CONTEXT_ALWAYS_KEEP_RECENT = int(os.getenv("CONTEXT_ALWAYS_KEEP_RECENT", "5"))
        self.STREAMING_ENABLED = os.getenv("STREAMING_ENABLED", "true").lower() == "true"
        self.STREAMING_PROGRESS_ENABLED = os.getenv("STREAMING_PROGRESS_ENABLED", "true").lower() == "true"
        
        # Max size for code injection via code_path= in KB. Prevents exceeding token limits.
        self.MAX_CODE_INJECTION_SIZE_KB = int(os.getenv("MAX_CODE_INJECTION_SIZE_KB", "512")) # Default to 512 KB

        # Allowed root directories for builtin tools (comma-separated paths)
        allowed_paths_str = os.getenv("ALLOWED_CODE_PATHS", "")
        if allowed_paths_str:
            # Parse and normalize paths
            self.ALLOWED_CODE_PATHS = [
                os.path.realpath(os.path.expanduser(p.strip())) 
                for p in allowed_paths_str.split(',') 
                if p.strip()
            ]
        else:
            # If not set, allow all paths (no restrictions)
            self.ALLOWED_CODE_PATHS = []

    def reload_api_key(self):
        """Reloads the API key from the key manager."""
        self.API_KEY = api_key_manager.get_active_key_value() or os.getenv("API_KEY", "")

    def set_api_key(self, new_key: str):
        """Updates the API key in memory and in the .env file."""
        self.API_KEY = new_key
        set_key('.env', 'API_KEY', new_key)

# Singleton instance of the config
config = AppConfig()
