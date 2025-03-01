"""
Code handling several basic commands (stats, version, config)
"""

from importlib.metadata import version as importlib_version
from hevelius import db
from hevelius.config import load_config
import datetime
import subprocess
import pathlib
from os import path


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

    config = load_config()

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


def backup(args):
    """
    Generated DB backup
    """

    backup_name = datetime.datetime.now().strftime("hevelius-backup-%Y-%m-%d-%H-%M-%S.psql")

    full_path = path.join(config.BACKUP_PATH, backup_name)

    pathlib.Path(config.BACKUP_PATH).mkdir(parents=True, exist_ok=True)

    psql = subprocess.Popen(["pg_dump", "-U", config.USER, "-h", config.HOST, "-p",
                            str(config.PORT), config.DBNAME, "-f", full_path])
    # this returns std output, (something else)
    output, _ = psql.communicate()

    print(f"Backup stored in {full_path}")
