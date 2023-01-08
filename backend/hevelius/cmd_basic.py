from hevelius import db, config

def stats(args):

    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)

    if (v == 0):
        print("Schema version is 0, can't show any stats")
        return

    stats = db.stats_print(cnx)

    print("\nStats by state:")
    by_state = db.stats_by_state(cnx)
    for id,name,cnt in by_state:
        print("%18s(%2d): %d" % (name, id, cnt))

    print("\nStats by user:")
    by_user = db.stats_by_user(cnx)
    for name, id, cnt in by_user:
        print("%18s(%2d): %d" % (name, id, cnt))

    cnx.close()

def version(args):
    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)
    cnx.close()

def config_show(args):
    """Shows current database configuration."""
    print("DB credentials:")
    print(f"DB type:  {config.TYPE}")
    print(f"User:     {config.USER}")
    print(f"Password: {config.PASSWORD}")
    print(f"Database: {config.DBNAME}")
    print(f"Host:     {config.HOST}")
    print(f"Port:     {config.PORT}")
