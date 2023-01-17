import psycopg2
from hevelius import config

def connect():
    try:
        conn = psycopg2.connect(database=config.DBNAME, user=config.USER, password=config.PASSWORD, host=config.HOST, port=config.PORT)
    except BaseException as e:
        print(f"ERROR: Failed to connect to DB: user={config.USER}, database={config.DBNAME}, host={config.HOST}, port={config.PORT}: {e}")
        raise
    return conn

def run_query(conn, query):
    cursor = conn.cursor() # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query)
    result = None
    try:
        result = cursor.fetchall()
    except BaseException as err:
        print(f"ERROR: Query {query} went wrong: {err}")
    conn.commit()
    cursor.close()
    return result
