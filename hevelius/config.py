
import os
import yaml
from pathlib import Path

# Default configuration
DEFAULT_CONFIG = {
    'DATABASE': {
        'TYPE': 'pgsql',
        'USER': 'hevelius',
        'DBNAME': 'hevelius',
        'HOST': 'localhost',
        'PORT': 5432,
        'PASSWORD': '',
    },
    'PATHS': {
        'REPO_PATH': '/mnt/volume1/astro',
        'BACKUP_PATH': '/mnt/volume1/astro/backup',
    },
    'JWT': {
        'SECRET_KEY': None,
    }
}

def load_config():
    """
    Load configuration from environment variables with fallback to config files.
    Priority: env vars > config.yml > config.yml.example > defaults
    """
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
        'HEVELIUS_DB_TYPE': ('DATABASE', 'TYPE'),
        'HEVELIUS_DB_USER': ('DATABASE', 'USER'),
        'HEVELIUS_DB_NAME': ('DATABASE', 'DBNAME'),
        'HEVELIUS_DB_HOST': ('DATABASE', 'HOST'),
        'HEVELIUS_DB_PORT': ('DATABASE', 'PORT'),
        'HEVELIUS_DB_PASSWORD': ('DATABASE', 'PASSWORD'),
        'HEVELIUS_REPO_PATH': ('PATHS', 'REPO_PATH'),
        'HEVELIUS_BACKUP_PATH': ('PATHS', 'BACKUP_PATH'),
        'JWT_SECRET_KEY': ('JWT', 'SECRET_KEY'),
    }

    for env_var, (section, key) in env_mapping.items():
        if os.getenv(env_var):
            if section not in config_dict:
                config_dict[section] = {}
            config_dict[section][key] = os.getenv(env_var)

    return config_dict

def config_get(cfg={}):
    """
    Returns a dictionary with database connection parameters, with defaults filled in.
    """
    result = cfg.copy()
    if 'database' not in result:
        result['database'] = DEFAULT_CONFIG['DATABASE']['DBNAME']
    if 'user' not in result:
        result['user'] = DEFAULT_CONFIG['DATABASE']['USER']
    if 'password' not in result:
        result['password'] = DEFAULT_CONFIG['DATABASE']['PASSWORD']
    if 'host' not in result:
        result['host'] = DEFAULT_CONFIG['DATABASE']['HOST']
    if 'port' not in result:
        result['port'] = DEFAULT_CONFIG['DATABASE']['PORT']
    return result
