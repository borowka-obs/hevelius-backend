#!/usr/bin/env python3

# This is an ugly hack. It should be removed.
import sys
sys.path.append("e:\\devel\\hevelius-proc")

from hevelius import db

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

    # then, get the 26th to 32nd chars, which should be the digits in J131878 string.
    tmp2 = tmp[26:32]
    t["id"] = int(tmp2)
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

tasks = read_csv("SubframeSelector_table.csv")

print("Found %d task(s)" % len(tasks))

cnx = db.connect()

for t in tasks:
    db.task_update(cnx, t["id"], t["fwhm"], t["eccentricity"])

cnx.close()