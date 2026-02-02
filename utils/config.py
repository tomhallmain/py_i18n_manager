import json
from pathlib import Path

from utils.utils import Utils


class ConfigManager:
    def __init__(self):
        self.config_dir = Path("configs")
        self.default_config_path = self.config_dir / "default_config.json"
        self.user_config_path = self.config_dir / "user_config.json"
        self.config = self.load_config()
        
        # Set default language if not specified or invalid
        current_locale = self.get('translation.default_locale')
        if not current_locale or not isinstance(current_locale, str) or len(current_locale) < 2:
            system_locale = Utils.get_default_user_language()
            if system_locale:
                self.set('translation.default_locale', system_locale)
                print(f"Using system language '{system_locale}' as default locale")
        
    def load_config(self):
        """Load configuration from files, merging user config with defaults."""
        # Load default config
        default_config = {}
        if self.default_config_path.exists():
            try:
                with open(self.default_config_path, 'r') as f:
                    default_config = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load default config: {e}")
        
        # Load user config if it exists
        user_config = {}
        if self.user_config_path.exists():
            try:
                with open(self.user_config_path, 'r') as f:
                    user_config = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load user config: {e}")
        
        # Merge configs, user config takes precedence
        return self.merge_configs(default_config, user_config)
    
    def merge_configs(self, default, user):
        """Recursively merge user config with default config."""
        merged = default.copy()
        
        for key, value in user.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self.merge_configs(merged[key], value)
            else:
                merged[key] = value
                
        return merged
    
    def save_user_config(self, config):
        """Save user configuration to file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.user_config_path, 'w') as f:
                json.dump(config, f, indent=4)
            self.config = self.load_config()  # Reload config
            return True
        except Exception as e:
            print(f"Error saving user config: {e}")
            return False
    
    def get(self, key, default=None):
        """Get a configuration value using dot notation."""
        try:
            value = self.config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key, value):
        """Set a configuration value using dot notation."""
        keys = key.split('.')
        current = self.config
        
        # Navigate to the correct nested location
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
            
        current[keys[-1]] = value
        return self.save_user_config(self.config)


# Single shared instance; all config reads/writes go through this.
config_manager = ConfigManager()
