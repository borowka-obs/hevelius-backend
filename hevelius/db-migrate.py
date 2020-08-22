#!/usr/bin/env python3

from hevelius import config
import mysql.connector

print("Hevelius db-migrate 0.1")
print("Attempting to connect to Hevelius database %s@%s as user %s" % (config.DBNAME, config.HOST, config.USER))


def version_get(cnx):
    query = 'SELECT * from schema_version'

    cursor = cnx.cursor()

    cursor.execute(query)

    for i in cursor:
        ver = i[0]

    cursor.close()

    print("Schema version detected %d" % ver)

    return ver

cnx = mysql.connector.connect(user=config.USER, password=config.PASSWORD, database=config.DBNAME, host=config.HOST, port=config.PORT)

v = version_get(cnx)

cnx.close()