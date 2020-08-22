#!/usr/bin/env python3

# This is an ugly hack. It should be removed.
import sys
sys.path.append("e:\\devel\\hevelius-proc")

from hevelius import db

print("Hevelius db-migrate 0.1")

cnx = db.connect()

v = db.version_get(cnx)

cnx.close()