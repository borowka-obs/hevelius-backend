#!/usr/bin/env python3

# This is an ugly hack. It should be removed.
import sys
sys.path.append(".")

import argparse

try:
    from hevelius import db
except ImportError:
    print("Make sure you have config.py filled in. Please copy config.py-example to config.py and fill it in.")
    sys.exit(-1)

def parse_task(l):
    """ Parses a string like this: Subframe,1,1,"E:/astro/nerpio/MTOA/2020Q2/SFDB_2020-05-12_00-39-28_J131878_MTOA_CV_1x1_0300s_NGC2403.fit",8.744279e-01,2.505002e+00,7.740531e-01,8.744279e-01,2.760000e+02,1.622958e+01,1.735582e+01,400,3.436380e-02,9.298809e-01,2.496715e+00,9.148272e-02,2.159095e-02,"2020-05-11 22:39:28" """

    f = l.split(",")
    t = {}
    fname = f[3]

    t["filename"] = fname
    t["weight"] = float(f[4])
    t["fwhm"] = float(f[5])
    t["eccentricity"] = float(f[6])
    t["snrweight"] = float(f[7])
    t["median"] = float(f[8])
    t["meandeviation"] = float(f[9])
    t["stars"] = float(f[11])

    # Now try to get the job id from the filename. First, ignore the path...
    tmp = fname[fname.rfind("/") + 1:]

    # then, get the J012345 substring, which designates the task id.
    try:
        offset = tmp.find("J") + 1
        tmp2 = tmp[offset:offset+6]
        t["id"] = int(tmp2)
    except ValueError:
        print("ERROR: Unable to parse task id from [%s], tmp=[%s] tmp2=[%s]" % (l, tmp, tmp2), file = sys.stderr)
        t["id"] = -1
    return t

def read_csv(fname):
    with open(fname) as f:
        content = f.readlines()

    tasks = []
    found = False
    i = 0
    for l in content:
        i += 1
        l = l.strip()
        if not found and l.find("SubframeHeader") == -1:
            continue
        if not found:
            found = True
            print("Data header found in line %d" % i)
            continue

        tasks.append(parse_task(l))

    return tasks


def cmd_subframe_selector(args):
    print("Loading file %s" % args.subframe_selector)

    tasks = read_csv(args.subframe_selector)

    print("Found %d task(s)" % len(tasks))

    cnx = db.connect()

    cnt = 0
    for t in tasks:
        print("Task %d of %d: " % (cnt, len(tasks)), end="")
        cnt += 1
        if (not args.dry_run):
            if t["id"] > 0:
                db.task_update(cnx, t["id"], t["fwhm"], t["eccentricity"])
            else:
                print("WARNING: skipping line %d, because task id is %d" % (cnt, t["id"]))
        else:
            print("Pretending to update task %d with fwhm=%f, eccentricity=%f" % (t["id"], t["fwhm"], t["eccentricity"]))

    cnx.close()


if __name__ == '__main__':

    parser = argparse.ArgumentParser("Hevelius Processor 0.1.0")
    parser.add_argument("-s", "--subframe-selector", help="SubframeSelector output CSV file.", type=str, required=True)
    parser.add_argument("-d", "--dry-run", help="Pretends to do updates.", action='store_true', default=False, required=False)

    args = parser.parse_args()

    cmd_subframe_selector(args)
