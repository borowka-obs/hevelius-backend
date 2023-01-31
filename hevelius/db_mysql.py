

import mysql.connector
from hevelius import config


def connect():
    try:
        cnx = mysql.connector.connect(user=config.USER, password=config.PASSWORD,
                                      database=config.DBNAME, host=config.HOST, port=config.PORT)
    except BaseException as e:
        print("ERROR: Failed to connect to DB: user=%s, database=%s, host=%s, port=%d: %s" % (
            config.USER, config.DBNAME, config.HOST, config.PORT, e))
        raise
    return cnx


def run_query(cnx, query):
    cursor = cnx.cursor()  # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query)
    try:
        result = cursor.fetchall()
    except mysql.connector.Error as err:
        print("ERROR: Running query failed: {}".format(err))
#    except:
#        #result = None # If this is an update or delete query.
#        cnx.commit()
    cnx.commit()
    cursor.close()
    return result
