import os
import yaml
from pathlib import Path

loaded_config = None

# Default configuration
DEFAULT_CONFIG = {
    'database': {
        'type': 'pgsql',
        'user': 'hevelius',
        'dbname': 'hevelius',
        'host': 'localhost',
        'port': 5432,
        'password': '',
    },
    'paths': {
        'repo-path': '/mnt/volume1/astro',
        'backup-path': '/mnt/volume1/astro/backup',
    },
    'jwt': {
        'secret-key': None,
    }
}

def load_config():
    """
    Load configuration from environment variables with fallback to config files.
    Priority: env vars > config.yml > config.yml.example > defaults
    """
    global loaded_config
    if loaded_config:
        return loaded_config

    config_dict = DEFAULT_CONFIG.copy()

    # Try loading from config files
    config_paths = [
        Path(__file__).parent / 'hevelius.yaml',
    ]

    for config_path in config_paths:
        if config_path.exists():
            print(f"####: {config_path} found")
            with open(config_path) as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    config_dict.update(file_config)
            break
        else:
            print(f"####: {config_path} not found")

    # Environment variables override file config
    env_mapping = {
        'HEVELIUS_DB_TYPE': ('database', 'type'),
        'HEVELIUS_DB_USER': ('database', 'user'),
        'HEVELIUS_DB_NAME': ('database', 'dbname'),
        'HEVELIUS_DB_HOST': ('database', 'host'),
        'HEVELIUS_DB_PORT': ('database', 'port'),
        'HEVELIUS_DB_PASSWORD': ('database', 'password'),
        'HEVELIUS_REPO_PATH': ('paths', 'repo-path'),
        'HEVELIUS_BACKUP_PATH': ('paths', 'backup-path'),
        'JWT_SECRET_KEY': ('jwt', 'secret-key'),
    }

    for env_var, (section, key) in env_mapping.items():
        if os.getenv(env_var):
            if section not in config_dict:
                config_dict[section] = {}
            config_dict[section][key] = os.getenv(env_var)

    loaded_config = config_dict

    return config_dict.copy()

def config_get(cfg={}):
    """
    Returns a dictionary with database connection parameters, with defaults filled in.
    """

    loaded_config = load_config()
    if loaded_config is None or 'database' not in loaded_config:
        raise Exception("Database configuration not found")

    result = load_config()['database']

    # Overwrite whatever is in the override config
    for key, value in cfg.items():
        result[key] = value

    result.pop('type', None)

    return result
