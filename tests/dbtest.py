import os
import hashlib
from functools import wraps
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from hevelius import config as hevelius_config
from hevelius.cmd_db_migrate import migrate_pgsql, run_file

# The relative path to the root directory.
_root_dir = os.path.dirname(os.path.realpath(__file__))
_root_dir = os.path.dirname(_root_dir)

# Dictionary to track created template databases by their data file
# Key: hash of load_test_data path (or "none"), Value: template database name
_template_dbs = {}


def _read_configuration():
    '''
    Read the configuration, returns 2 configs:
    1. management DB ("postgres" or "template1")
    2. test DB (the DB to be created)
    '''

    config = hevelius_config.load_config()

    return ({
        "database": config['database']['database'],
        "user": config['database']['user'],
        "host": config['database']['host'],
        "port": config['database']['port'],
        "password": config['database']['password']
    }, {
        "database": config['database']['database'] + "_test",
        "user": config['database']['user'],
        "password": config['database']['password'],
        "host": config['database']['host'],
        "port": config['database']['port']
    })


def _get_template_suffix(load_test_data: str) -> str:
    '''Generate a short suffix for template database name based on test data file.'''
    if load_test_data is None:
        return "nodata"
    # Use a short hash of the file path to create unique template names
    return hashlib.md5(load_test_data.encode()).hexdigest()[:8]


def _standard_seed_db(config, load_test_data: str):
    '''Migrate and seed the test database using incremental migrations.'''
    migrate_pgsql({"dry_run": False}, cfg=config)

    if load_test_data is not None:
        print(f"Loading test data from file {load_test_data}")
        run_file(config, load_test_data)
    else:
        print("Skipping loading data.")


def _fast_seed_db(config, load_test_data: str):
    '''Seed the test database using consolidated schema (faster for tests).'''
    from hevelius import db

    consolidated_schema = os.path.join(_root_dir, "db", "schema-consolidated.psql")

    if not os.path.exists(consolidated_schema):
        print(f"Consolidated schema not found at {consolidated_schema}, falling back to incremental migrations")
        _standard_seed_db(config, load_test_data)
        return

    print(f"Using consolidated schema from {consolidated_schema}")
    run_file(config, consolidated_schema)

    if load_test_data is not None:
        print(f"Loading test data from file {load_test_data}")
        run_file(config, load_test_data)
    else:
        print("Skipping loading data.")


def _create_template_database(mgmt_config, template_config, load_test_data: str):
    '''Create a template database with schema and test data.

    This template can be used to quickly create test databases via PostgreSQL's
    CREATE DATABASE ... TEMPLATE feature, which is much faster than running
    migrations for each test.
    '''
    global _template_dbs

    template_key = _get_template_suffix(load_test_data)
    template_db_name = template_config['database']

    if template_key in _template_dbs:
        print(f"Template database {template_db_name} already exists for this test data")
        return

    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    try:
        # Drop template if it exists from a previous failed run
        drop_db_query = f"DROP DATABASE IF EXISTS {template_db_name};"
        maintenance_cursor.execute(drop_db_query)

        # Create the template database
        create_database_query = f"CREATE DATABASE {template_db_name} OWNER {template_config['user']};"
        maintenance_cursor.execute(create_database_query)

        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        print(f"Failed to create template DB. Exception: {e}")
        raise

    # Seed the template database
    _fast_seed_db(template_config, load_test_data)

    _template_dbs[template_key] = template_db_name
    print(f"Template database {template_db_name} created successfully")


def _create_db_from_template(mgmt_config, test_config, template_db_name):
    '''Create a test database from a template (very fast).'''
    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    try:
        # Drop test DB if it exists
        drop_db_query = f"DROP DATABASE IF EXISTS {test_config['database']};"
        maintenance_cursor.execute(drop_db_query)

        # Create test database from template
        create_database_query = f"CREATE DATABASE {test_config['database']} TEMPLATE {template_db_name} OWNER {test_config['user']};"
        maintenance_cursor.execute(create_database_query)

        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        print(f"Failed to create test DB from template. Exception: {e}")
        raise


def _use_fast_tests():
    '''Check if fast tests should be used.

    Fast tests use a template database approach which is much faster.
    Set HEVELIUS_SLOW_TESTS=1 to disable this and use incremental migrations.
    '''
    return not os.environ.get("HEVELIUS_SLOW_TESTS")


@contextmanager
def setup_database_test_case(*, load_test_data: str = None):
    '''Create the test database, migrate it to the latest version, and
    destroy after test case.

    If HEVELIUS_SLOW_TESTS is not set (default), uses template database
    approach for faster test execution. The template is created once per
    test session with the consolidated schema.

    If HEVELIUS_SLOW_TESTS=1, uses incremental migrations (slower but tests
    the actual migration path).
    '''
    mgmt_config, test_config = _read_configuration()

    use_fast = _use_fast_tests()

    if use_fast:
        # Template database approach (fast)
        # Use different template for different test data files
        template_suffix = _get_template_suffix(load_test_data)
        template_db_name = test_config['database'] + "_tpl_" + template_suffix
        template_config = {**test_config, 'database': template_db_name}

        # Create template database if it doesn't exist
        _create_template_database(mgmt_config, template_config, load_test_data)

        # Create test database from template (very fast)
        _create_db_from_template(mgmt_config, test_config, template_db_name)

    else:
        # Original slow approach with incremental migrations
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if os.environ.get("HEVELIUS_DEBUG"):
            maintenance_connection.autocommit = True

        # If previous run failed and didn't cease the database, drop it.
        try:
            drop_db_query = f"DROP DATABASE IF EXISTS {test_config['database']};"
            maintenance_cursor.execute(drop_db_query)

            create_database_query = f"CREATE DATABASE {test_config['database']} OWNER {test_config['user']};"
            maintenance_cursor.execute(create_database_query)

            maintenance_cursor.close()
            maintenance_connection.close()
        except Exception as e:
            print(f"Failed to create DB. You might want to do (ALTER USER hevelius CREATEDB) and run again. Exception: {e}")

        _standard_seed_db(test_config, load_test_data)

    try:
        yield test_config
    finally:
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if os.environ.get("HEVELIUS_DEBUG"):
            print(f"HEVELIUS_DEBUG is set, not dropping the test database ({test_config['database']}).")
        else:
            drop_database_query = f"DROP DATABASE IF EXISTS {test_config['database']};"
            print(f"Dropping the test database ({test_config['database']}).")
            maintenance_cursor.execute(drop_database_query)

        maintenance_cursor.close()
        maintenance_connection.close()


def cleanup_template_database():
    '''Clean up all template databases at the end of the test session.

    This should be called by pytest's session-scoped fixture or manually
    after all tests complete.
    '''
    global _template_dbs

    if not _template_dbs:
        return

    mgmt_config, _ = _read_configuration()

    try:
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if not os.environ.get("HEVELIUS_DEBUG"):
            for template_key, template_db_name in _template_dbs.items():
                drop_db_query = f"DROP DATABASE IF EXISTS {template_db_name};"
                maintenance_cursor.execute(drop_db_query)
                print(f"Dropped template database {template_db_name}")

        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        print(f"Failed to drop template database: {e}")

    _template_dbs.clear()


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
