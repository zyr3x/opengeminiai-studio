import json
import os
import uuid
from threading import RLock

class AIProviderManager:
    def __init__(self, config_path='var/config/ai_providers.json'):
        self.config_path = config_path
        self.lock = RLock()
        self.providers_data = {'providers': {}, 'active_provider_id': None, 'model_map': {}}
        self.model_provider_map = {}  # Cache: model_id -> provider_id
        self.load_providers()

    def load_providers(self):
        with self.lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r') as f:
                        self.providers_data = json.load(f)
                except json.JSONDecodeError:
                    self.providers_data = {'providers': {}, 'active_provider_id': None, 'model_map': {}}
            
            # Initialize model_map from loaded data if exists
            if 'model_map' in self.providers_data:
                self.model_provider_map = self.providers_data['model_map'].copy()
            else:
                self.providers_data['model_map'] = {}

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
            if 'base_url' not in provider_data: 
                provider_data['base_url'] = ''
            
            # Clean base_url (strip trailing slash)
            if provider_data['base_url'].endswith('/'):
                provider_data['base_url'] = provider_data['base_url'].rstrip('/')
            
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

    def get_provider_by_name(self, name):
        """Finds the provider config for a given provider name."""
        with self.lock:
            for p_id, provider in self.providers_data.get('providers', {}).items():
                if provider.get('name') == name:
                    return provider
            return None

    def get_all_providers_data(self):
        with self.lock:
            return self.providers_data.copy()

    def register_model(self, model_id, provider_id):
        """Registers a model to a specific provider to route requests correctly."""
        with self.lock:
            self.model_provider_map[model_id] = provider_id
            # Also update persistent data
            if 'model_map' not in self.providers_data:
                self.providers_data['model_map'] = {}
            self.providers_data['model_map'][model_id] = provider_id
            
    def is_model_registered(self, model_id):
        """Checks if a specific model is registered to a custom provider."""
        with self.lock:
            return model_id in self.model_provider_map

    def get_provider_for_model(self, model_id):
        """Finds the provider config for a given model ID."""
        with self.lock:
            # 1. Try specific mapping
            if model_id in self.model_provider_map:
                p_id = self.model_provider_map[model_id]
                if p_id in self.providers_data['providers']:
                    return self.providers_data['providers'][p_id]
            
            # 2. Try active provider (fallback)
            active = self.get_active_provider()
            if active:
                return active
                
            # 3. Try any provider
            if self.providers_data['providers']:
                return list(self.providers_data['providers'].values())[0]
            
            return None

ai_provider_manager = AIProviderManager()
