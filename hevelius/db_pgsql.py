import psycopg2


def connect(config):

    try:
        # supported parameters: user, password, database, host, port
        cfg = config.copy()
        cfg.pop('type', None)
        conn = psycopg2.connect(**cfg)
        conn.autocommit = True
    except BaseException as e:
        print(
            f"ERROR: Failed to connect to DB: user={config['user']}, database={config['database']}, host={config['host']}, port={config['port']}: {e}")
        raise
    return conn


def run_query(conn, query, values=None):
    cursor = conn.cursor()  # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query, values)
    result = None

    if (query.strip().lower().startswith("select")):
        try:
            result = cursor.fetchall()
        except BaseException as err:
            print(f"ERROR: Query {query} went wrong: {type(err)} {err}")
    elif (query.strip().lower().startswith("insert")):
        try:
            result = cursor.fetchone()[0]  # Try to fetch if RETURNING is used
        except psycopg2.ProgrammingError:
            # No results to fetch (INSERT without RETURNING)
            conn.commit()  # Make sure the changes are committed
            result = None
    else:
        conn.commit()  # For other statements (UPDATE, DELETE, etc.)

    cursor.close()
    return result
