import os
from dotenv import load_dotenv, set_key
from app.utils.core.api_key_manager import api_key_manager
load_dotenv()
class AppConfig:
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
        self.MIN_CONTEXT_CACHING_TOKENS = int(os.getenv("MIN_CONTEXT_CACHING_TOKENS", "2048"))
        self.MAX_CODE_INJECTION_SIZE_KB = int(os.getenv("MAX_CODE_INJECTION_SIZE_KB", "256"))
        self.ETC_DIR =  os.path.realpath(os.path.expanduser(os.getenv("ETC_DIR", "etc/")))
        self.VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"
        self.DEBUG_CLIENT_LOGGING = os.getenv("DEBUG_CLIENT_LOGGING", "true").lower() == "true"
        allowed_paths_str = os.getenv("ALLOWED_CODE_PATHS", "")
        if allowed_paths_str:
            self.ALLOWED_CODE_PATHS = [
                os.path.realpath(os.path.expanduser(p.strip())) 
                for p in allowed_paths_str.split(',') 
                if p.strip()
            ]
        else:
            self.ALLOWED_CODE_PATHS = []
        self.FAVICON = ''
        with open(os.path.realpath(os.path.expanduser("static/img/logo.svg")), 'r', encoding='utf-8', errors='ignore') as f:
            self.FAVICON = f.read()
    def set_param(self, name: str, value: str):
        setattr(self, name, value)
        set_key('.env', name, str(value))
    def get_param(self, name: str):
        return getattr(self, name, None)
    def reload_api_key(self):
        self.API_KEY = api_key_manager.get_active_key_value() or os.getenv("API_KEY", "")
    def set_api_key(self, new_key: str):
        self.API_KEY = new_key
        set_key('.env', 'API_KEY', new_key)
config = AppConfig()