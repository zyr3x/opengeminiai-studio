import json
import os
import uuid
from threading import RLock

class AIProviderManager:
    def __init__(self, config_path='var/config/ai_providers.json'):
        self.config_path = config_path
        self.lock = RLock()
        self.providers_data = {'providers': {}, 'active_provider_id': None}
        self.load_providers()

    def load_providers(self):
        with self.lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r') as f:
                        self.providers_data = json.load(f)
                except json.JSONDecodeError:
                    self.providers_data = {'providers': {}, 'active_provider_id': None}
            
            # If no providers loaded, check env vars for legacy config to migrate/default
            if not self.providers_data.get('providers'):
                base_url = os.getenv("OPENAI_BASE_URL")
                if base_url:
                    default_id = "default_env"
                    self.providers_data['providers'] = {
                        default_id: {
                            "id": default_id,
                            "name": "Default (from .env)",
                            "base_url": base_url,
                            "api_key": os.getenv("OPENAI_API_KEY", ""),
                            "model": os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")
                        }
                    }
                    self.providers_data['active_provider_id'] = default_id
                    self.save_providers()

    def save_providers(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.providers_data, f, indent=4)

    def add_or_update_provider(self, provider_data):
        with self.lock:
            p_id = provider_data.get('id')
            if not p_id:
                p_id = str(uuid.uuid4())
                provider_data['id'] = p_id
            
            # Ensure mandatory fields have defaults if missing
            if 'name' not in provider_data: provider_data['name'] = 'Unnamed Provider'
            if 'base_url' not in provider_data: provider_data['base_url'] = ''
            
            self.providers_data['providers'][p_id] = provider_data
            
            # If it's the first one or requested, make it active
            if not self.providers_data['active_provider_id']:
                self.providers_data['active_provider_id'] = p_id
                
            self.save_providers()
            return p_id

    def delete_provider(self, provider_id):
        with self.lock:
            if provider_id in self.providers_data['providers']:
                del self.providers_data['providers'][provider_id]
                if self.providers_data['active_provider_id'] == provider_id:
                    self.providers_data['active_provider_id'] = None
                    # Fallback to another if exists
                    if self.providers_data['providers']:
                        self.providers_data['active_provider_id'] = list(self.providers_data['providers'].keys())[0]
                self.save_providers()
                return True
            return False

    def set_active_provider(self, provider_id):
        with self.lock:
            if provider_id in self.providers_data['providers']:
                self.providers_data['active_provider_id'] = provider_id
                self.save_providers()
                return True
            return False

    def get_active_provider(self):
        with self.lock:
            active_id = self.providers_data.get('active_provider_id')
            if active_id and active_id in self.providers_data['providers']:
                return self.providers_data['providers'][active_id]
            return None

    def get_all_providers_data(self):
        with self.lock:
            return self.providers_data.copy()

ai_provider_manager = AIProviderManager()
