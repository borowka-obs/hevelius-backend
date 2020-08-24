#!/usr/bin/env python3

# This is an ugly hack. It should be removed.
import sys
sys.path.append(".")

from hevelius import db
import argparse

def stats(args):
    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)

    stats = db.stats_get(cnx)
    print("There are %d tasks, %d files, %d have FWHM, %d have eccentricity." % stats)
    print("Missing: %d files miss FWHM, %d files miss eccentricity." % (stats[1] - stats[2], stats[1] - stats[3]))

    print("Stats by state:")
    by_state = db.stats_by_state(cnx)
    for id,name,cnt in by_state:
        print("%18s(%2d): %d" % (name, id, cnt))

    cnx.close()

if __name__ == '__main__':
    print("Hevelius db-migrate 0.1")

    parser = argparse.ArgumentParser("Hevelius DB Migrator 0.1.0")

    args = parser.parse_args()

    stats(args)

