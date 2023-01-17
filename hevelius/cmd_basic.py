"""
Code handling several basic commands (stats, version, config)
"""

from importlib.metadata import version as importlib_version
from hevelius import db, config


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

    print("DB credentials:")
    print(f"DB type:  {config.TYPE}")
    print(f"User:     {config.USER}")
    print(f"Password: {config.PASSWORD}")
    print(f"Database: {config.DBNAME}")
    print(f"Host:     {config.HOST}")
    print(f"Port:     {config.PORT}")
