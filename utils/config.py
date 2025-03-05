import json
import os
from pathlib import Path
from utils.utils import Utils


class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs")

    def __init__(self):
        self.dict = {}
        self.foreground_color = None
        self.background_color = None

        self.server_port = 6000
        self.server_password = "<PASSWORD>"
        self.server_host = "localhost"

        configs =  [ f.path for f in os.scandir(Config.CONFIGS_DIR_LOC) if f.is_file() and f.path.endswith(".json") ]
        self.config_path = None

        for c in configs:
            if os.path.basename(c) == "config.json":
                self.config_path = c
                break
            elif os.path.basename(c) != "config_example.json":
                self.config_path = c

        if self.config_path is None:
            self.config_path = os.path.join(Config.CONFIGS_DIR_LOC, "config_example.json")

        try:
            self.dict = json.load(open(self.config_path, "r"))
        except Exception as e:
            print(e)
            print("Unable to load config. Ensure config.json file settings are correct.")

        self.set_values(str,
                        "foreground_color",
                        "background_color",
        )
        # self.set_values(list,
        # self.set_values(dict, 
        # self.set_directories(
        # self.set_filepaths(

    def validate_and_set_directory(self, key, override=False):
        loc = key if override else self.dict[key]
        if loc and loc.strip() != "":
            if "{HOME}" in loc:
                loc = loc.strip().replace("{HOME}", os.path.expanduser("~"))
            if not os.path.isdir(loc):
                raise Exception(f"Invalid location provided for {key}: {loc}")
            return loc
        return None

    def validate_and_set_filepath(self, key):
        filepath = self.dict[key]
        if filepath and filepath.strip() != "":
            if "{HOME}" in filepath:
                filepath = filepath.strip().replace("{HOME}", os.path.expanduser("~"))
            if not os.path.isfile(filepath):
                raise Exception(f"Invalid location provided for {key}: {filepath}")
            return filepath
        return None

    def set_directories(self, *directories):
        for directory in directories:
            # try:
            setattr(self, directory, self.validate_and_set_directory(directory))
            # except Exception as e:
            #     print(e)
            #     print(f"Failed to set {directory} from config.json file. Ensure the key is set.")

    def set_filepaths(self, *filepaths):
        for filepath in filepaths:
            try:
                setattr(self, filepath, self.validate_and_set_filepath(filepath))
            except Exception as e:
                pass
#                print(e)
#                print(f"Failed to set {filepath} from config.json file. Ensure the key is set.")

    def set_values(self, type, *names):
        for name in names:
            if type:
                try:
                    setattr(self, name, type(self.dict[name]))
                except Exception as e:
                    pass
#                    print(e)
#                    print(f"Failed to set {name} from config.json file. Ensure the value is set and of the correct type.")
            else:
                try:
                    setattr(self, name, self.dict[name])
                except Exception as e:
                    pass
#                    print(e)
#                    print(f"Failed to set {name} from config.json file. Ensure the key is set.")



config = Config()

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
