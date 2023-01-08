from hevelius import config, db
from os import listdir,pathsep
from os.path import isfile, join

def migrate(args):
    if config.TYPE == "pgsql":
        migrate_pgsql(args)
    elif config.TYPE == "mysql":
        migrate_mysql(args)
    else:
        print(f"ERROR: Invalid database type specified in config.py: {config.TYPE}")
        sys.exit(-1)

def migrate_mysql(args):

    DIR = "db"
    files = [f for f in listdir(DIR) if (isfile(join(DIR, f)) and f.endswith("mysql"))   ]

    files.sort()

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        mig_ver = int(f[:2])

        if (mig_ver > current_ver):
            print("Migrating from %s to %s, using script %s" % (current_ver, mig_ver, f))

            schema = subprocess.Popen(["cat", join(DIR,f)], stdout=subprocess.PIPE)

            mysql = subprocess.Popen(["mysql", "-u", config.USER, "-h", config.HOST, "-p"+config.PASSWORD, "-P", str(config.PORT), config.DBNAME, "-B"], stdin=schema.stdout)

            schema.stdout.close()
            output, _ = mysql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print("Version after schema upgrade %s" % current_ver)

        else:
            print("Skipping %s, schema version is %s" % (f, current_ver))

def migrate_pgsql(args):

    DIR = "db"
    files = [f for f in listdir(DIR) if (isfile(join(DIR, f)) and f.endswith("psql"))]

    files.sort()

    for f in files:
        cnx = db.connect()
        current_ver = db.version_get(cnx)
        cnx.close()

        try:
            mig_ver = int(f[:2])
        except:
            # Skip files that don't start with a number (such as wipe.psql)
            continue

        if (mig_ver > current_ver):
            print("Migrating from %s to %s, using script %s" % (current_ver, mig_ver, f))

            #schema = subprocess.Popen(["cat", join(DIR,f)], stdout=subprocess.PIPE)

            # TODO: pass password in PGPASSWORD variable (from config.PASSWORD)
            psql = subprocess.Popen(["psql", "-U", config.USER, "-h", config.HOST, "-p", str(config.PORT), config.DBNAME, "-f", DIR + "/" + f])

            #schema.stdout.close()
            output, _ = psql.communicate()

            cnx = db.connect()
            current_ver = db.version_get(cnx)
            cnx.close()

            print("Version after schema upgrade %s" % current_ver)

        else:
            print("Skipping %s, schema version is %s" % (f, current_ver))
