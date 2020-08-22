#!/usr/bin/env python3

# This is an ugly hack. It should be removed.
import sys
sys.path.append("e:\\devel\\hevelius-proc")

import pprint

from hevelius import db

print("Hevelius db-migrate 0.1")

cnx = db.connect()

v = db.version_get(cnx)

print("Schema version is %d" % v)

stats = db.stats_get(cnx)
print("There are %d tasks, %d files." % stats)

print("Stats by state:")
by_state = db.stats_by_state(cnx)
print(by_state)

print("Status of task 133989: BEFORE")
t1 = db.task_get(cnx, 133989)
print(t1)

db.task_update(cnx, 133989, fwhm = 12.34, eccentricity=54.321)

print("Status of task 133989: AFTER")
t1 = db.task_get(cnx, 133989)
print(t1)


#t2 = db.task_get(cnx, 133910)
#print(t2)

cnx.close()