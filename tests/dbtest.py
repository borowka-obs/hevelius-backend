import os
import atexit
from functools import wraps
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from hevelius import config as hevelius_config, db
from hevelius.cmd_db_migrate import migrate_pgsql, run_file

# The relative path to the root directory.
_root_dir = os.path.dirname(os.path.realpath(__file__))
_root_dir = os.path.dirname(_root_dir)

# One migrated template DB per run: first test creates it, rest clone from it.
_test_template_name = None


def _read_configuration():
    '''
    Read the configuration, returns 2 configs:
    1. management DB: always "postgres" so we can DROP/CREATE the test DB
       (never use project DB name here, as it may be "hevelius_test" from env)
    2. test DB (the DB to be created)
    '''
    config = hevelius_config.load_config()
    base_db = config['database']['database']
    # If env left HEVELIUS_DB_NAME=hevelius_test, base_db could be hevelius_test;
    # derive the intended test DB name (suffix _test only if not already present).
    if base_db.endswith('_test'):
        test_db_name = base_db
    else:
        test_db_name = base_db + '_test'

    return ({
        "database": "postgres",
        "user": config['database']['user'],
        "host": config['database']['host'],
        "port": config['database']['port'],
        "password": config['database']['password']
    }, {
        "database": test_db_name,
        "user": config['database']['user'],
        "password": config['database']['password'],
        "host": config['database']['host'],
        "port": config['database']['port']
    })


def _reset_sequences_after_load(test_config):
    """Reset serial sequences to max(id) so inserts get new ids (test data uses explicit ids)."""
    conn = db.connect(test_config)
    try:
        db.run_query(
            conn,
            "SELECT setval(pg_get_serial_sequence('filters', 'filter_id'), "
            "COALESCE((SELECT MAX(filter_id) FROM filters), 1))"
        )
        db.run_query(
            conn,
            "SELECT setval(pg_get_serial_sequence('sensors', 'sensor_id'), "
            "COALESCE((SELECT MAX(sensor_id) FROM sensors), 1))"
        )
        db.run_query(
            conn,
            "SELECT setval(pg_get_serial_sequence('projects', 'project_id'), "
            "COALESCE((SELECT MAX(project_id) FROM projects), 1))"
        )
        db.run_query(
            conn,
            "SELECT setval(pg_get_serial_sequence('project_subframes', 'id'), "
            "COALESCE((SELECT MAX(id) FROM project_subframes), 1))"
        )
    finally:
        conn.close()


def _drop_test_template():
    '''Drop the shared template DB at process exit.'''
    global _test_template_name
    if _test_template_name is None:
        return
    try:
        mgmt_config, _ = _read_configuration()
        conn = psycopg2.connect(**mgmt_config)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {_test_template_name};")
        cur.close()
        conn.close()
    except Exception:  # pragma: no cover
        pass
    _test_template_name = None


@contextmanager
def setup_database_test_case(*, load_test_data: str = None):
    '''Create the test database, migrate it to the latest version (or clone from
    template after first run), and destroy after test case.'''
    global _test_template_name
    mgmt_config, test_config = _read_configuration()
    test_db_name = test_config['database']
    template_name = test_db_name + "_template"

    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    if os.environ.get("HEVELIUS_DEBUG"):
        maintenance_connection.autocommit = True

    try:
        # Drop test DB if it exists (e.g. from a crashed run)
        maintenance_cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name};")

        if _test_template_name is None:
            # First run: create DB, run full migration, then create template for next time
            maintenance_cursor.execute(
                f"CREATE DATABASE {test_db_name} OWNER {test_config['user']};"
            )
            maintenance_cursor.close()
            maintenance_connection.close()

            migrate_pgsql({"dry_run": False}, cfg=test_config)

            maintenance_connection = psycopg2.connect(**mgmt_config)
            maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            maintenance_cursor = maintenance_connection.cursor()
            # Terminate other connections so we can use the DB as template (PostgreSQL
            # requires no connections to the source DB when creating a template)
            maintenance_cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid();",
                (test_db_name,)
            )
            maintenance_cursor.execute(
                f"CREATE DATABASE {template_name} WITH TEMPLATE {test_db_name} OWNER {test_config['user']};"
            )
            _test_template_name = template_name
            atexit.register(_drop_test_template)

            maintenance_cursor.execute(f"DROP DATABASE {test_db_name};")
            maintenance_cursor.execute(
                f"CREATE DATABASE {test_db_name} WITH TEMPLATE {template_name} OWNER {test_config['user']};"
            )
        else:
            # Reuse: create test DB from existing template (no migration)
            maintenance_cursor.execute(
                f"CREATE DATABASE {test_db_name} WITH TEMPLATE {_test_template_name} OWNER {test_config['user']};"
            )

        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        maintenance_cursor.close()
        maintenance_connection.close()
        print(f"Failed to create DB. You might want to do (ALTER USER {test_config['user']} CREATEDB) and run again. Exception: {e}")
        raise

    if load_test_data is not None:
        print(f"Loading test data from file {load_test_data}")
        run_file(test_config, load_test_data)
        # Reset sequences so next INSERT gets a new id (test data uses explicit ids)
        _reset_sequences_after_load(test_config)
    else:
        print("Skipping loading data.")

    try:
        yield test_config
    finally:
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if os.environ.get("HEVELIUS_DEBUG"):
            print(f"HEVELIUS_DEBUG is set, not dropping the test database ({test_db_name}).")
        else:
            maintenance_cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name};")

        maintenance_cursor.close()
        maintenance_connection.close()


def use_repository(f=None, *, load_test_data="tests/test-data.psql"):
    '''The test case decorator that passes the repository object
    as the first argument. The repository uses the test database.
    The database is destroyed after the test case.

    Args:
        f: The function to decorate (when used without parameters)
        load_test_data: If True (default), loads test data into the database
    '''
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            with setup_database_test_case(load_test_data=load_test_data) as config:
                return func(self, config, *args, **kwargs)
        return wrapper

    # Handle both @use_repository and @use_repository(load_test_data=False) cases
    if f is None:
        return decorator
    return decorator(f)
