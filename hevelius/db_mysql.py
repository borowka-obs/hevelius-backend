import mysql.connector


def connect(config):
    try:
        # supported parameters: user, password, database, host, port
        cnx = mysql.connector.connect(**config)
    except BaseException as e:
        print(f"ERROR: Failed to connect to DB: user={config['user']}, database={config['dbname']}, host={config['host']}, port={config['port']}: {e}")
        raise
    return cnx


def run_query(cnx, query, params=None):
    cursor = cnx.cursor()  # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query, params)
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
