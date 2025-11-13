import json
import os
from threading import RLock

class APIKeyManager:
    def __init__(self, config_path='var/config/api_keys.json'):
        self.config_path = config_path
        self.lock = RLock()
        self.keys_data = {'keys': {}, 'active_key_id': None}
        self.load_keys()
    def load_keys(self):
        with self.lock:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.keys_data = json.load(f)
            else:
                legacy_api_key = os.getenv('API_KEY')
                if legacy_api_key:
                    self.keys_data['keys']['legacy_default'] = legacy_api_key
                    self.keys_data['active_key_id'] = 'legacy_default'
                    self.save_keys()
    def save_keys(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.keys_data, f, indent=4)
    def add_or_update_key(self, key_id, key_value):
        with self.lock:
            self.keys_data['keys'][key_id] = key_value
            self.save_keys()
    def delete_key(self, key_id):
        with self.lock:
            if key_id in self.keys_data['keys']:
                del self.keys_data['keys'][key_id]
                if self.keys_data['active_key_id'] == key_id:
                    self.keys_data['active_key_id'] = None
                self.save_keys()
                return True
            return False
    def set_active_key(self, key_id):
        with self.lock:
            if key_id in self.keys_data['keys']:
                self.keys_data['active_key_id'] = key_id
                self.save_keys()
                return True
            return False
    def get_active_key_value(self):
        with self.lock:
            active_id = self.keys_data.get('active_key_id')
            if active_id and active_id in self.keys_data['keys']:
                return self.keys_data['keys'][active_id]
            return os.getenv('API_KEY')
    def get_all_keys_data(self):
        with self.lock:
            return self.keys_data.copy()
api_key_manager = APIKeyManager()
