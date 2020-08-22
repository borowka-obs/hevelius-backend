

import mysql.connector
from hevelius import config

def connect():
    cnx = mysql.connector.connect(user=config.USER, password=config.PASSWORD, database=config.DBNAME, host=config.HOST, port=config.PORT)
    return cnx

def version_get(cnx):
    query = 'SELECT * from schema_version'
    cursor = cnx.cursor()
    cursor.execute(query)

    for i in cursor:
        ver = i[0]

    cursor.close()
    print("Schema version detected %d" % ver)
    return ver
