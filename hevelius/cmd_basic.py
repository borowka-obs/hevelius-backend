"""
Code handling several basic commands (stats, version, config)
"""

from importlib.metadata import version as importlib_version
from hevelius import db, config


def stats():
    """
    Prints database statistics (version, overall, by state, by user)

    :param args: arguments parsed by argparse
    """

    cnx = db.connect()

    ver = db.version_get(cnx)

    print(f"Schema version is {ver}")

    if ver == 0:
        print("DB not initialized (schema version is 0), can't show any stats")
        return

    db.stats_print(cnx)

    print("\nStats by state:")
    by_state = db.stats_by_state(cnx)
    for state_id, name, cnt in by_state:
        print(f"{name:>18}({state_id:2}): {cnt}")

    print("\nStats by user:")
    by_user = db.stats_by_user(cnx)
    for name, user_id, cnt in by_user:
        print(f"{name:>18}({user_id:2}): {cnt}")

    cnx.close()


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
