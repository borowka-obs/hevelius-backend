import sys

try:
    from hevelius import config
except ImportError:
    print("ERROR: Make sure you have config.py filled in. Please copy config.py-example to config.py and fill it in.")
    sys.exit(-1)

if config.TYPE == "pgsql":
    import hevelius.db_pgsql as backend
elif config.TYPE == "mysql":
    import hevelius.db_mysql as backend
else:
    print(
        f"ERROR: Invalid database type specified in config.py: {config.TYPE}")
    sys.exit(-1)


def connect():
    return backend.connect()


def run_query(conn, query):
    return backend.run_query(conn, query)


def version_get(cnx):
    query = 'SELECT * from schema_version'
    cursor = cnx.cursor()

    ver = ""
    try:
        cursor.execute(query)
    except:
        # Table doesn't exist, return 0
        return 0

    for i in cursor:
        ver = i[0]

    cursor.close()
    return int(ver)


def stats_print(cnx):

    stats = [
        ("true", "all tasks"),
        ("imagename is not null", "with images"),
        ("he_solved = 1",            "solved"),
        ("he_solved is null",        "not solved (not attempted)"),
        ("he_solved = 0",            "not solved (attempted, but failed)"),
        ("he_fwhm is not null", "with quality measured (FWHM != null)"),
        ("eccentricity is not null", "with quality measured (eccen != null)"),

    ]

    for cond, descr in stats:
        q = "SELECT count(*) FROM tasks WHERE %s" % cond

        result = run_query(cnx, q)[0][0]

        print("Tasks %40s: %d" % (descr, result))

    # Get overall tasks counters
    # tasks_cnt = run_query(cnx, 'SELECT count(*) from tasks')[0][0]
    # files_cnt = run_query(cnx, 'SELECT count(*) from tasks where imagename is not null')[0][0]

    # fwhm_cnt = run_query(cnx, 'select count(*) from tasks WHERE fwhm is not null')
    # eccentricity_cnt = run_query(cnx, 'select count(*) from tasks WHERE eccentricity is not null')

    # print("There are %d tasks, %d files, %d have FWHM, %d have eccentricity." % stats)
    # print("Missing: %d files miss FWHM, %d files miss eccentricity." % (stats[1] - stats[2], stats[1] - stats[3]))

    # return tasks_cnt[0][0], files_cnt[0][0], fwhm_cnt[0][0], eccentricity_cnt[0][0]


def stats_by_state(cnx):
    # Get tasks list by status
    hist = run_query(
        cnx, 'SELECT id, name, count(*) FROM tasks, states WHERE tasks.state = states.id GROUP BY state, id, name ORDER BY id')
    res = []

    for row in hist:
        res.append((row[0], row[1], row[2]))

    return res


def stats_by_user(cnx, state=6):
    if state is None:
        cond = ""
    else:
        cond = "AND state = %d" % state

    q = "SELECT login, tasks.user_id, count(*) FROM tasks, users WHERE tasks.user_id = users.user_id %s GROUP BY tasks.user_id,users.login ORDER BY login;" % cond

    tasks_per_user = run_query(cnx, q)

    res = []
    for row in tasks_per_user:
        res.append((row[0], row[1], row[2]))
    return res


def task_get(cnx, id):
    q = "SELECT task_id, state, user_id, imagename, object, descr, comment, ra, decl, exposure, filter, binning, guiding, fwhm, eccentricity FROM tasks WHERE task_id = %d" % id

    t = run_query(cnx, q)[0]

    x = {}
    x["id"] = t[0]
    x["state"] = t[1]
    x["user_id"] = t[2]
    x["file"] = t[3]
    x["object"] = t[4]
    x["descr"] = t[5]
    x["comment"] = t[6]
    x["ra"] = t[7]
    x["decl"] = t[8]
    x["exposure"] = t[9]
    x["filter"] = t[10]
    x["binning"] = t[11]
    x["guiding"] = t[12]
    x["fwhm"] = t[13]
    x["eccentricity"] = t[14]

    return x


def task_exists(cnx, task_id):
    """Check if task defined by task_id exists."""
    v = run_query(cnx, f"SELECT count(*) FROM tasks where task_id={task_id}")
    return v[0][0] == 1


def tasks_get_filter(cnx, criteria):
    q = f"SELECT state,task_id, imagename, object, he_solved_ra, he_solved_dec, exposure, filter, binning, fwhm, eccentricity FROM tasks WHERE {criteria}"

    tasks = run_query(cnx, q)

    print(f"Selected {len(tasks)} task(s)")

    return tasks


def task_update(cnx, id, fwhm=None, eccentricity=None):
    upd = ""
    if fwhm is not None:
        upd = "fwhm = %f" % fwhm
    if eccentricity is not None:
        if len(upd):
            upd += ", "
        upd += "eccentricity = %f" % eccentricity

    if not len(upd):
        print("Nothing to update in task %d, aborting" % id)

    q = "UPDATE tasks SET %s WHERE task_id=%d" % (upd, id)

    print("Updating task %d: query=[%s]" % (id, q))

    run_query(cnx, q)


def field_names(t, names):
    """Returns a coma separated list of fields, if they exist in the t dictionary.
    names is a array of strings."""
    q = ""
    for name in names:
        if name in t:
            if len(q):
                q += ", "
            q += name
    return q


def field_values(t, names):
    """Returns a coma separated list of field values, if they exist in the t dictionary.
    names is a array of strings."""
    q = ""
    for name in names:
        if name in t:
            if len(q):
                q += ", "
            q += "'" + str(t[name]) + "'"
    return q


def field_check(t, names):
    """Checks if all expected field names are present. Returns true if they
    are."""

    for name in names:
        if not name in t:
            print(f"ERROR: Required field {name} missing in {t}")
            return False
    return True


def task_add(cnx, task, verbose = False, dry_run = False):
    """Inserts new task.
       cnx - connection
       task - dictionary representing a task
       dry_run - whether really add a task or not,

       return: True if added, False if not"""

    if not field_check(task, ["user_id"]):
        print("ERROR: Required field(s) missing, can't add a task.")

    fields = ["task_id", "user_id", "scope_id", "state", "object", "filter", "binning", "exposure",
              "solve", "solved", "calibrate", "calibrated", "imagename"]

    q = "INSERT INTO tasks(" + field_names(task, fields) + ") "
    q += "VALUES(" + field_values(task, fields) + ")"

    if verbose:
        print(f"Inserting task: {q}")

    if not dry_run:
        result = run_query(cnx, q)
        print(f"Task {task['task_id']} inserted.")
        return True
    else:
        print(f"Dry-run: would add a task {task['task_id']}.")
        return False

def user_get_id(cnx, aavso_id=None, login=None):

    q = "SELECT user_id FROM users WHERE "
    if aavso_id:
        q += f"aavso_id='{aavso_id}'"
    if login:
        q += f"login='{login}'"

    v = run_query(cnx, q)
    return v[0][0]
