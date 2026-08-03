"""
Code handling several basic commands (stats, version, config)
"""

import datetime
import pathlib
import subprocess
from importlib.metadata import version as importlib_version
from os import environ, path

from hevelius import db
from hevelius.config import load_config
from hevelius.version import VERSION


def db_version():
    """
    Prints the database schema version.

    :param args: arguments parsed by argparse
    """
    cnx = db.connect()

    ver = db.version_get(cnx)

    print(f"Schema version is {ver}")
    cnx.close()


def hevelius_version() -> str:
    """
    Prints the Hevelius code version.

    :return: string representing version (or empty string)
    """
    if VERSION:
        return VERSION

    try:
        return importlib_version('hevelius')
    except ModuleNotFoundError:
        # Oh well, hevelius is not installed. We're running from source tree
        pass

    # TODO: try to parse setup.py and get version='x.y.z' from it.
    return ""


def config_show():
    """
    Shows current database configuration.

    :param args: arguments parsed by argparse
    """

    config, config_metadata = load_config(return_metadata=True)

    print("Configuration source:")
    if config_metadata['base_source'] == 'file':
        print(f"Base config file: {config_metadata['base_config_path']}")
    else:
        print("Base config file: not found (using built-in defaults)")
    if config_metadata['environment_overrides']:
        print("Environment overrides: " + ", ".join(config_metadata['environment_overrides']))
    else:
        print("Environment overrides: none")

    print()

    print("DB credentials:")
    print(f"Type:     {config['database']['type']}")
    print(f"User:     {config['database']['user']}")
    print(f"Password: {config['database']['password']}")
    print(f"Database: {config['database']['database']}")
    print(f"Host:     {config['database']['host']}")
    print(f"Port:     {config['database']['port']}")

    print()

    print(f"Files repository path: {config['paths']['repo-path']}")
    print(f"Backup storage path:   {config['paths']['backup-path']}")


# Tables holding data for each --skip-* backup option. Small lookup tables
# (task_states, asteroid_tags) are kept regardless, since they're tiny and
# other tables' FKs may reference them.
SKIP_TASKS_TABLES = ('tasks', 'task_projects')
SKIP_PROJECTS_TABLES = ('projects', 'project_subframes', 'project_users', 'task_projects')
SKIP_MINOR_PLANETS_TABLES = ('asteroids', 'asteroid_tag_map')


def _format_size(num_bytes: int) -> str:
    """Human-readable file size."""
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def backup(args):
    """
    Generated DB backup
    """

    backup_name = datetime.datetime.now().strftime("hevelius-backup-%Y-%m-%d-%H-%M-%S.psql")

    config = load_config()

    full_path = path.join(config['paths']['backup-path'], backup_name)

    pathlib.Path(config['paths']['backup-path']).mkdir(parents=True, exist_ok=True)

    my_env = environ.copy()
    my_env['PGPASSWORD'] = config['database']['password']

    skip_tables = set()
    if getattr(args, 'skip_tasks', False):
        skip_tables.update(SKIP_TASKS_TABLES)
    if getattr(args, 'skip_projects', False):
        skip_tables.update(SKIP_PROJECTS_TABLES)
    if getattr(args, 'skip_minor_planets', False):
        skip_tables.update(SKIP_MINOR_PLANETS_TABLES)

    cmd = ["pg_dump", "-U", config['database']['user'], "-h", config['database']['host'], "-p",
           str(config['database']['port'])]
    for table in sorted(skip_tables):
        cmd += ["--exclude-table-data", table]
    cmd += [config['database']['database'], "-f", full_path]

    psql = subprocess.Popen(cmd, env=my_env)
    psql.communicate()

    pg_dump_version = subprocess.run(
        ["pg_dump", "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()

    if psql.returncode != 0 or not path.exists(full_path):
        if path.exists(full_path):
            try:
                pathlib.Path(full_path).unlink()
            except OSError as err:
                print(f"Warning: could not remove incomplete backup {full_path}: {err}")
        print(f"pg_dump failed (exit code {psql.returncode}); no backup was stored.")
        return 1

    print(f"Backup stored in {full_path}")
    print(f"Backup size: {_format_size(path.getsize(full_path))}")
    print(f"PostgreSQL version used to export: {pg_dump_version}")
    return 0
