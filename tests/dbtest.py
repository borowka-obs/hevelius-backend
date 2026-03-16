import os
import hashlib
from functools import wraps
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from hevelius import config as hevelius_config, db
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


def _get_template_suffix(load_test_data: str) -> str:
    """Generate a short suffix for template database name based on test data file."""
    if load_test_data is None:
        return "nodata"
    # Use a short hash of the file path to create unique template names
    return hashlib.md5(load_test_data.encode()).hexdigest()[:8]


def _standard_seed_db(config, load_test_data: str):
    """Migrate and seed the test database using incremental migrations."""
    migrate_pgsql({"dry_run": False}, cfg=config)

    if load_test_data is not None:
        print(f"Loading test data from file {load_test_data}")
        run_file(config, load_test_data)
        _reset_sequences_after_load(config)
    else:
        print("Skipping loading data.")


def _fast_seed_db(config, load_test_data: str):
    """Seed the test database using consolidated schema (faster for tests)."""
    consolidated_schema = os.path.join(_root_dir, "db", "schema-consolidated.psql")

    if not os.path.exists(consolidated_schema):
        print(f"Consolidated schema not found at {consolidated_schema}, falling back to incremental migrations")
        _standard_seed_db(config, load_test_data)
        return

    print(f"Using consolidated schema from {consolidated_schema}")
    run_file(config, consolidated_schema)

    # Bring schema up to the latest version (applies migrations after the consolidated snapshot).
    migrate_pgsql({"dry_run": False}, cfg=config)

    if load_test_data is not None:
        print(f"Loading test data from file {load_test_data}")
        run_file(config, load_test_data)
        _reset_sequences_after_load(config)
    else:
        print("Skipping loading data.")


def _create_template_database(mgmt_config, template_config, load_test_data: str):
    """Create a template database with schema and test data for fast cloning."""
    global _template_dbs

    template_key = _get_template_suffix(load_test_data)
    template_db_name = template_config['database']

    if template_key in _template_dbs:
        return

    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    try:
        maintenance_cursor.execute(f"DROP DATABASE IF EXISTS {template_db_name};")
        maintenance_cursor.execute(
            f"CREATE DATABASE {template_db_name} OWNER {template_config['user']};"
        )
        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        print(f"Failed to create template DB. Exception: {e}")
        raise

    _fast_seed_db(template_config, load_test_data)

    _template_dbs[template_key] = template_db_name


def _create_db_from_template(mgmt_config, test_config, template_db_name):
    """Create a test database from a template (very fast)."""
    maintenance_connection = psycopg2.connect(**mgmt_config)
    maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    maintenance_cursor = maintenance_connection.cursor()

    try:
        maintenance_cursor.execute(
            f"DROP DATABASE IF EXISTS {test_config['database']};"
        )
        maintenance_cursor.execute(
            f"CREATE DATABASE {test_config['database']} TEMPLATE {template_db_name} OWNER {test_config['user']};"
        )
        maintenance_cursor.close()
        maintenance_connection.close()
    except Exception as e:
        print(f"Failed to create test DB from template. Exception: {e}")
        raise


def _use_fast_tests():
    """Determine whether to use the fast template-based test DB path."""
    return not os.environ.get("HEVELIUS_SLOW_TESTS")


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
    '''Create the test database, migrate it to the latest version, and
    destroy after test case.

    If HEVELIUS_SLOW_TESTS is not set (default), uses template database
    approach for faster test execution. The template is created once per
    test data file with the consolidated schema and subsequent migrations.

    If HEVELIUS_SLOW_TESTS=1, uses incremental migrations (slower but tests
    the actual migration path).
    '''
    mgmt_config, test_config = _read_configuration()

    use_fast = _use_fast_tests()

    if use_fast:
        template_suffix = _get_template_suffix(load_test_data)
        template_db_name = test_config['database'] + "_tpl_" + template_suffix
        template_config = {**test_config, 'database': template_db_name}

        _create_template_database(mgmt_config, template_config, load_test_data)
        _create_db_from_template(mgmt_config, test_config, template_db_name)
    else:
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
            print(f"Failed to create DB. You might want to do (ALTER USER {test_config['user']} CREATEDB) and run again. Exception: {e}")

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
            maintenance_cursor.execute(
                f"DROP DATABASE IF EXISTS {test_config['database']};"
            )

        maintenance_cursor.close()
        maintenance_connection.close()


def cleanup_template_database():
    '''Clean up all template databases at the end of the test session.'''
    global _template_dbs

    if not _template_dbs:
        return

    mgmt_config, _ = _read_configuration()

    try:
        maintenance_connection = psycopg2.connect(**mgmt_config)
        maintenance_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        maintenance_cursor = maintenance_connection.cursor()

        if not os.environ.get("HEVELIUS_DEBUG"):
            for template_db_name in _template_dbs.values():
                maintenance_cursor.execute(
                    f"DROP DATABASE IF EXISTS {template_db_name};"
                )

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
