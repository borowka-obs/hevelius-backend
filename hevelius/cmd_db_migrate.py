"""
Code handing database migrations.

Historically, the system was using MySQL, not migrated to Postgres now.
The last schema version using MySQL was 6. 7 and later are Postgres based.
"""

from os import listdir, environ
from os.path import isfile, join
import subprocess
import sys
from hevelius import db
from hevelius.config import config_db_get


def generate_consolidated_schema(output_path="db/schema-consolidated.psql"):
    """
    Generate a consolidated PostgreSQL schema file for testing.

    This creates a fresh temporary database, runs all migrations to bring it
    to the latest schema version, and then dumps the schema (no data) to
    ``output_path`` using ``pg_dump --schema-only``.
    """

    cfg = config_db_get()
    if cfg["type"] != "pgsql":
        print("Consolidated schema generation is only supported for PostgreSQL.")
        sys.exit(1)

    base_db = cfg["database"]
    temp_db = base_db + "_consolidated_tmp"

    # Connect to the management database (postgres) to create/drop the temp db.
    mgmt_cfg = {**cfg, "database": "postgres"}

    conn = db.connect(mgmt_cfg)
    conn.set_session(autocommit=True)
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {temp_db};")
        cur.execute(f"CREATE DATABASE {temp_db} OWNER {cfg['user']};")
    finally:
        cur.close()
        conn.close()

    # Run migrations against the temporary database.
    migrate_pgsql({"dry_run": False}, cfg={**cfg, "database": temp_db})

    # Dump schema only from the temporary database.
    my_env = environ.copy()
    my_env["PGPASSWORD"] = cfg["password"]

    with open(output_path, "w") as out:
        proc = subprocess.Popen(
            [
                "pg_dump",
                "--schema-only",
                "-U",
                cfg["user"],
                "-h",
                cfg["host"],
                "-p",
                str(cfg["port"]),
                temp_db,
            ],
            stdout=out,
            env=my_env,
        )
        proc.wait()

    # Drop the temporary database.
    conn = db.connect(mgmt_cfg)
    conn.set_session(autocommit=True)
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {temp_db};")
    finally:
        cur.close()
        conn.close()


def migrate(args):
    """
    Conducts database migration to the newest schema.

    :param args: arguments parsed by argparse
    """

    config = config_db_get()

    if config['type'] == "pgsql":
        migrate_pgsql(args)
    elif config['type'] == "mysql":
        migrate_mysql(args)
    else:
        print(
            f"ERROR: Invalid database type specified in config.py: {config.TYPE}, allowed are: mysql, pgsql")
        sys.exit(-1)


def migrate_mysql(args, cfg={}):
    """
    Performs MySQL database migration to the newest schema.

    :param args: arguments parsed by argparse
    """

    # Fill in the defaults of DB connection, if not specified
    cfg = config_db_get(cfg)

    dir = "db"
    files = sorted([f for f in listdir(dir) if (
        isfile(join(dir, f)) and f.endswith("mysql"))])

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        mig_ver = int(f[:2])

        if mig_ver > current_ver:
            print(
                f"Migrating from {current_ver} to {mig_ver}, using script {f}")

            if not args.dry_run:
                schema = subprocess.Popen(
                    ["cat", join(dir, f)], stdout=subprocess.PIPE)
                mysql = subprocess.Popen(["mysql", "-u", cfg['user'], "-h", cfg['host'],
                                          "-p" +
                                          cfg['password'], "-P", str(cfg['port']),
                                          cfg['dbname'], "-B"], stdin=schema.stdout)
            else:
                print("Skipping (--dry-run).")

            output, _ = mysql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print(f"Version after schema upgrade {current_ver}")

        else:
            print(f"Skipping {f}, schema version is {current_ver}")


def run_file(cfg, filename):
    """
    Runs SQL commands from a file.
    """

    # Fill in the defaults of DB connection, if not specified
    cfg = config_db_get(cfg)

    conn = db.connect(cfg)

    with open(filename, "r") as f:
        sql = f.read()
        db.run_query(conn, sql)

    conn.close()


def migrate_pgsql(args, cfg={}):
    """
    Performs PostgreSQL database migration to the newest schema.

    :param args: arguments parsed by argparse
    """

    # Fill in the defaults of DB connection, if not specified
    cfg = config_db_get(cfg)

    dry_run = args.get('dry_run') if isinstance(args, dict) else args.dry_run

    DIR = "db"
    files = sorted([f for f in listdir(DIR) if (
        isfile(join(DIR, f)) and f.endswith("psql"))])

    for f in files:
        cnx = db.connect(cfg)
        current_ver = db.version_get(cnx)
        cnx.close()

        try:
            mig_ver = int(f[:2])
        except BaseException:
            # Skip files that don't start with a number (such as wipe.psql)
            continue

        if mig_ver > current_ver:
            print(
                f"Migrating from {current_ver} to {mig_ver}, using script {f}")

            if not dry_run:
                my_env = environ.copy()
                my_env['PGPASSWORD'] = cfg['password']

                psql = subprocess.Popen(["psql", "-U", cfg['user'], "-h", cfg['host'], "-p",
                                        str(cfg['port']), cfg['database'], "-f", DIR + "/" + f],
                                        stdout=subprocess.PIPE, env=my_env)
                output = ""
                for line in iter(psql.stdout.readline, b''):
                    output += line.decode('utf-8').rstrip()

                # TODO: make sure the output is printable, if a variable is set
                # print(output)

            else:
                print("Skipping (--dry-run).")

            # this returns std output, (something else)
            _, _ = psql.communicate()

            cnx = db.connect(cfg)
            current_ver = db.version_get(cnx)
            cnx.close()

        else:
            print(f"Skipping {f}, schema version is {current_ver}")
