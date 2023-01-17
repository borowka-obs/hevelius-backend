"""
Code handing database migrations.

Historically, the system was using MySQL, not migrated to Postgres now.
The last schema version using MySQL was 6. 7 and later are Postgres based.
"""

from os import listdir
from os.path import isfile, join
import subprocess
import sys
from hevelius import config, db


def migrate(args):
    """
    Conducts database migration to the newest schema.

    :param args: arguments parsed by argparse
    """
    if config.TYPE == "pgsql":
        migrate_pgsql(args)
    elif config.TYPE == "mysql":
        migrate_mysql(args)
    else:
        print(
            f"ERROR: Invalid database type specified in config.py: {config.TYPE}, allowed are: mysql, pgsql")
        sys.exit(-1)


def migrate_mysql(args):
    """
    Performs MySQL database migration to the newest schema.

    :param args: arguments parsed by argparse
    """

    DIR = "db"
    files = [f for f in listdir(DIR) if (
        isfile(join(DIR, f)) and f.endswith("mysql"))]

    files.sort()

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        mig_ver = int(f[:2])

        if mig_ver > current_ver:
            print(
                f"Migrating from {current_ver} to {mig_ver}, using script {f}")

            schema = subprocess.Popen(
                ["cat", join(DIR, f)], stdout=subprocess.PIPE)

            mysql = subprocess.Popen(["mysql", "-u", config.USER, "-h", config.HOST,
                                     "-p" +
                                      config.PASSWORD, "-P", str(config.PORT),
                                      config.DBNAME, "-B"], stdin=schema.stdout)

            output, _ = mysql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print(f"Version after schema upgrade {current_ver}")

        else:
            print(f"Skipping {f}, schema version is {current_ver}")


def migrate_pgsql(args):
    """
    Performs PostgreSQL database migration to the newest schema.

    :param args: arguments parsed by argparse
    """

    DIR = "db"
    files = [f for f in listdir(DIR) if (
        isfile(join(DIR, f)) and f.endswith("psql"))]

    files.sort()

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        try:
            mig_ver = int(f[:2])
        except:
            # Skip files that don't start with a number (such as wipe.psql)
            continue

        if mig_ver > current_ver:
            print(
                f"Migrating from {current_ver} to {mig_ver}, using script {f}")

            # schema = subprocess.Popen(["cat", join(DIR,f)], stdout=subprocess.PIPE)

            # TODO: pass password in PGPASSWORD variable (from config.PASSWORD)
            psql = subprocess.Popen(["psql", "-U", config.USER, "-h", config.HOST, "-p",
                                     str(config.PORT), config.DBNAME, "-f", DIR + "/" + f])

            # schema.stdout.close()
            output, _ = psql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print(f"Version after schema upgrade {current_ver}")

        else:
            print(f"Skipping {f}, schema version is {current_ver}")
