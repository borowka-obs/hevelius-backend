#!/usr/bin/env python3

from os import listdir
from os.path import isfile, join
import sys
import subprocess
import argparse

# This is an ugly hack. It should be removed.
sys.path.append(".")
from hevelius import db
from hevelius import config

def stats(args):

    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)

    if (v == 0):
        print("Schema version is 0, can't show any stats")
        return

    stats = db.stats_get(cnx)
    print("There are %d tasks, %d files, %d have FWHM, %d have eccentricity." % stats)
    print("Missing: %d files miss FWHM, %d files miss eccentricity." % (stats[1] - stats[2], stats[1] - stats[3]))

    print("Stats by state:")
    by_state = db.stats_by_state(cnx)
    for id,name,cnt in by_state:
        print("%18s(%2d): %d" % (name, id, cnt))

    cnx.close()

def version(args):
    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)
    cnx.close()

def migrate(args):

    DIR = "db"
    files = [f for f in listdir(DIR) if (isfile(join(DIR, f)) and f.endswith("mysql"))   ]

    files.sort()

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        mig_ver = int(f[:2])

        if (mig_ver > current_ver):
            print("Migrating from %s to %s, using script %s" % (current_ver, mig_ver, f))

            schema = subprocess.Popen(["cat", join(DIR,f)], stdout=subprocess.PIPE)

            mysql = subprocess.Popen(["mysql", "-u", config.USER, "-h", config.HOST, "-p"+config.PASSWORD, "-P", str(config.PORT), config.DBNAME, "-B"], stdin=schema.stdout)

            schema.stdout.close()
            output, _ = mysql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print("Version after schema upgrade %s" % current_ver)

        else:
            print("Skipping %s, schema version is %s" % (f, current_ver))




if __name__ == '__main__':
    print("Hevelius db-migrate 0.1")

    parser = argparse.ArgumentParser("Hevelius DB Migrator 0.1.0")
    subparsers = parser.add_subparsers(help="commands", dest="command")

    stats_parser = subparsers.add_parser('stats', help="Show database statistics")
    migrate_parser = subparsers.add_parser('migrate', help="Migrate to the latest DB schema")
    version_parser = subparsers.add_parser('version', help="Shows the current DB schema version.")

    args = parser.parse_args()

    if args.command == "stats":
        stats(args)
    elif args.command == "migrate":
        migrate(args)
    elif args.command == "version":
        version(args)

    else:
        parser.print_help()
