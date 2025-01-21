import psycopg2


def connect(config):

    try:
        # supported parameters: user, password, database, host, port
        conn = psycopg2.connect(**config)
    except BaseException as e:
        print(
            f"ERROR: Failed to connect to DB: user={config['user']}, database={config['database']}, host={config['host']}, port={config['port']}: {e}")
        raise
    return conn


def run_query(conn, query):
    cursor = conn.cursor()  # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query)
    result = None

    if (query.strip().lower().startswith("select")):
        try:
            result = cursor.fetchall()
        except BaseException as err:
            print(f"ERROR: Query {query} went wrong: {type(err)} {err}")
    else:
        conn.commit()

    cursor.close()
    return result
