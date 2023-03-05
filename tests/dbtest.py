import os
from functools import wraps
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from hevelius import config
from hevelius.cmd_db_migrate import migrate_pgsql

# The relative path to the root directory.
_root_dir = os.path.dirname(os.path.realpath(__file__))
_root_dir = os.path.dirname(_root_dir)


def _read_configuration():
    '''
    Read the configuration, returns 2 configs:
    1. management DB ("postgres" or "template1")
    2. test DB (the DB to be created)
    '''

    return ({
        "database": config.DBNAME,
        "user": config.USER,
        "host": config.HOST,
        "port": config.PORT,
        "password": config.PASSWORD
    }, {
        "database": config.DBNAME + "_test",
        "user": config.USER,
        "password": config.PASSWORD,
        "host": config.HOST,
        "port": config.PORT
    })


def _standard_seed_db(config):
    '''Migrate and seed the test database.'''
    migrate_pgsql({"dry_run": False}, cfg=config)


@contextmanager
def setup_database_test_case():
    '''Create the test database, migrate it to the latest version, and
    destroy after test case.'''
    mgmt_config, test_config = _read_configuration()

    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    # If previous run failed and didn't cease the database, drop it.
    drop_db_query = f"DROP DATABASE IF EXISTS {test_config['database']};"
    maintenance_cursor.execute(drop_db_query)

    create_database_query = f"CREATE DATABASE {test_config['database']} OWNER {test_config['user']};"
    maintenance_cursor.execute(create_database_query)

    maintenance_cursor.close()
    maintenance_connection.close()

    _standard_seed_db(test_config)

    try:
        yield test_config
    finally:
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if os.environ.get("HEVELIUS_DEBUG"):
            print("HEVELIUS_DEBUG is set, not dropping the test database.")
        else:
            drop_database_query = f"DROP DATABASE {test_config['database']};"
            print(f"HEVELIUS_DEBUG not set, dropping database: {test_config['database']}")
            maintenance_cursor.execute(drop_database_query)

        maintenance_cursor.close()
        maintenance_connection.close()


def use_repository(f):
    '''The test case decorator that passes the repository object
    as the first argument. The repository uses the test database.
    The database is destroyed after the test case.'''
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        with setup_database_test_case() as config:
            return f(self, config, *args, **kwargs)
    return wrapper
