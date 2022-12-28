#!/usr/bin/env python3

import sys
import argparse
import numpy as np
import pandas as pd
import plotly.express as px

# This is an ugly hack. It should be removed.
sys.path.append(".")

try:
    from hevelius import db_mysql as db
except ImportError:
    print("Make sure you have config.py filled in. Please copy config.py-example to config.py and fill it in.")
    sys.exit(-1)
from hevelius import config

def stats(args):

    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)

    if (v == 0):
        print("Schema version is 0, can't show any stats")
        return

    stats = db.stats_print(cnx)

    print("\nStats by state:")
    by_state = db.stats_by_state(cnx)
    for id,name,cnt in by_state:
        print("%18s(%2d): %d" % (name, id, cnt))

    print("\nStats by user:")
    by_user = db.stats_by_user(cnx)
    for name, id, cnt in by_user:
        print("%18s(%2d): %d" % (name, id, cnt))

    cnx.close()

def select_tasks(args):
    cnx = db.connect()

    tasks = db.tasks_get_filter(cnx, "imagename is not null AND he_solved_ra is not null AND state = 6")

    cnx.close()

    # This gets a list of coords (0-359, -90..90)
    histo = np.zeros((180,360))
    for t in tasks:
        ra = int(t[4])
        decl = int(t[5])
        histo[decl,ra] += 1


    pandas = pd.DataFrame(histo)
    fig = px.imshow(pandas)
    fig.show()


if __name__ == '__main__':
    print("Hevelius process 0.1")

    parser = argparse.ArgumentParser("Hevelius Tasks Processor 0.1")
    subparsers = parser.add_subparsers(help="commands", dest="command")

    stats_parser = subparsers.add_parser('stats', help="Show database statistics")
    select_parser = subparsers.add_parser('select', help="Selects some tasks")

    args = parser.parse_args()

    if args.command == "stats":
        stats(args)
    elif args.command == "select":
        select_tasks(args)

    else:
        parser.print_help()
