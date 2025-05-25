"""
An abstract interface to databases (PostgreSQL or MySQL).
Depending on the configuration, it imports either
hevelius.db_pgsql or hevelius.db_mysql.
"""

from typing import List
import sys
import hevelius.config as hevelius_config


# Load configuration
config = hevelius_config.load_config()

# Configure database backend
if config['database']['type'] == "pgsql":
    import hevelius.db_pgsql as backend
elif config['database']['type'] == "mysql":
    import hevelius.db_mysql as backend
else:
    print(f"ERROR: Invalid database type specified: {config['database']['type']}")
    sys.exit(-1)


def connect(cfg={}):
    """
    Opens connection to a database, returns DB connection object.
    """

    cfg = hevelius_config.config_db_get(cfg)

    return backend.connect(cfg)


def run_query(conn, query, values=None):
    """
    Runs specified SQL query
    """
    return backend.run_query(conn, query, values)


def version_get(conn) -> int:
    """
    Retrieves database schema version from the database.
    """
    query = 'SELECT * from schema_version'
    cursor = conn.cursor()

    ver = ""
    try:
        cursor.execute(query)
    except BaseException:
        # Table doesn't exist, return 0
        return 0

    for i in cursor:
        ver = i[0]

    cursor.close()
    return int(ver)


def stats_print(conn):
    """
    Retrieves and prints various statistics.
    """

    stats = [
        ("true", "all tasks"),
        ("imagename is not null", "with images"),
        ("he_solved = 1", "solved"),
        ("he_solved is null", "not solved (not attempted)"),
        ("he_solved = 0", "not solved (attempted, but failed)"),
        ("he_fwhm is not null", "with quality measured (FWHM != null)"),
        ("eccentricity is not null", "with quality measured (eccen != null)"),

    ]

    for cond, descr in stats:
        query = f"SELECT count(*) FROM tasks WHERE {cond}"

        result = run_query(conn, query)[0][0]

        print("Tasks %40s: %d" % (descr, result))

    # Get overall tasks counters
    # tasks_cnt = run_query(cnx, 'SELECT count(*) from tasks')[0][0]
    # files_cnt = run_query(cnx, 'SELECT count(*) from tasks where imagename is not null')[0][0]

    # fwhm_cnt = run_query(cnx, 'select count(*) from tasks WHERE fwhm is not null')
    # eccentricity_cnt = run_query(cnx, 'select count(*) from tasks WHERE eccentricity is not null')

    # print("There are %d tasks, %d files, %d have FWHM, %d have eccentricity." % stats)
    # print("Missing: %d files miss FWHM, %d files miss eccentricity." % (stats[1] - stats[2], stats[1] - stats[3]))

    # return tasks_cnt[0][0], files_cnt[0][0], fwhm_cnt[0][0], eccentricity_cnt[0][0]


def stats_by_state(conn):
    """
    Retrieves task statistics per task state.
    """
    # Get tasks list by status
    hist = run_query(conn, 'SELECT id, name, count(*) FROM tasks, task_states WHERE tasks.state = task_states.id GROUP BY state, id, name ORDER BY id')
    res = []

    for row in hist:
        res.append((row[0], row[1], row[2]))

    return res


def stats_by_user(conn, state=6):
    """
    returns tuple with statistics by user
    """
    if state is None:
        cond = ""
    else:
        cond = f"AND state = {state}"

    q = "SELECT login, tasks.user_id, count(*) "\
        "FROM tasks, users "\
        f"WHERE tasks.user_id = users.user_id {cond} GROUP BY tasks.user_id,users.login ORDER BY login;"

    tasks_per_user = run_query(conn, q)

    res = []
    for row in tasks_per_user:
        res.append((row[0], row[1], row[2]))
    return res


def task_get(conn, id):
    """
    Retrieves a task with all parameters.
    """
    q = "SELECT task_id, state, user_id, imagename, object, descr, comment, ra, decl, exposure, filter, binning, guiding, he_fwhm, eccentricity "\
        "FROM tasks "\
        f"WHERE task_id = {id}"

    t = run_query(conn, q)[0]

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


def task_exists(conn, task_id):
    """Check if task defined by task_id exists."""
    v = run_query(conn, f"SELECT count(*) FROM tasks where task_id={task_id}")
    return v[0][0] == 1


def tasks_get_filter(conn, criteria):
    query = "SELECT state,task_id, imagename, object, he_solved_ra, he_solved_dec, exposure, filter, binning, he_fwhm, eccentricity "\
        "FROM tasks "\
        f"WHERE {criteria}"

    tasks = run_query(conn, query)

    print(f"Selected {len(tasks)} task(s)")

    return tasks


def task_update(conn, id, fwhm=None, eccentricity=None):
    upd = ""
    if fwhm is not None:
        upd = "fwhm = %f" % fwhm
    if eccentricity is not None:
        if len(upd):
            upd += ", "
        upd += "eccentricity = %f" % eccentricity

    if not len(upd):
        print(f"Nothing to update in task {id}, aborting")

    query = f"UPDATE tasks SET {upd} WHERE task_id={id}"

    print("Updating task %d: query=[%s]" % (id, query))

    run_query(conn, query)


def field_names(t, names):
    """Returns a coma separated list of fields, if they exist in the t dictionary.
    names is a array of strings."""
    query = ""
    for name in names:
        if name in t:
            if len(query):
                query += ", "
            query += name
    return query


def field_values(t, names):
    """Returns a coma separated list of field values, if they exist in the t dictionary.
    names is a array of strings."""
    query = ""
    for name in names:
        if name in t:
            if len(query):
                query += ", "
            query += "'" + str(t[name]) + "'"
    return query


def field_check(t, names):
    """Checks if all expected field names are present. Returns true if they
    are."""

    for name in names:
        if name not in t:
            print(f"ERROR: Required field {name} missing in {t}")
            return False
    return True


def task_add(conn, task, verbose=False, dry_run=False):
    """Inserts new task.
       cnx - connection
       task - dictionary representing a task
       dry_run - whether really add a task or not,

       return: True if added, False if not"""

    if not field_check(task, ["user_id"]):
        print("ERROR: Required field(s) missing, can't add a task.")

    fields = ["task_id", "user_id", "scope_id", "state", "object", "filter", "binning", "exposure",
              "solve", "solved", "calibrate", "calibrated", "imagename"]

    query = "INSERT INTO tasks(" + field_names(task, fields) + ") "
    query += "VALUES(" + field_values(task, fields) + ")"

    if verbose:
        print(f"Inserting task: {query}")

    if not dry_run:
        result = run_query(conn, query)
        print(f"Task {task['task_id']} inserted, result: {result}.")
        return True
    else:
        print(f"Dry-run: would add a task {task['task_id']}.")
        return False


def user_get_id(conn, aavso_id=None, login=None) -> str:
    """
    Retrieves an user_id for specified user.
    """

    query = "SELECT user_id FROM users WHERE "
    if aavso_id:
        query += f"aavso_id='{aavso_id}'"
    if login:
        query += f"login='{login}'"

    v = run_query(conn, query)
    return v[0][0]


def catalog_radius_get(conn, ra: float, decl: float, radius: float, order: str = "") -> List:
    """
    Returns objects from the catalogs that are close (within radius degrees) to
    the specified RA/DEC coordinates.

    Useful links:
    - https://physics.stackexchange.com/questions/224950/how-can-i-convert-right-ascension-and-declination-to-distances
    - https://en.wikipedia.org/wiki/Haversine_formula

    Uses the Haversine formula for proper spherical distance calculation.
    RA must be in hours (0-24), Dec in degrees (-90 to +90).
    """

    ra *= 15.0  # Specified in hours, convert to degrees

    # Haversine formula in SQL
    query = """
        SELECT object_id, name, altname, ra, decl
        FROM objects
        WHERE degrees(2 * asin(sqrt(
            pow(sin(radians(decl - {decl}) / 2), 2) +
            cos(radians({decl})) * cos(radians(decl)) *
            pow(sin(radians(ra*15 - {ra}) / 2), 2)
        ))) < {radius}
    """.format(ra=ra, decl=decl, radius=radius)

    if order:
        query += f" ORDER BY {order}"

    result = run_query(conn, query)

    return result


def catalog_get(conn, name: str) -> List:
    """
    Returns an object of specified name
    """
    query = f"SELECT object_id, name, altname, ra, decl FROM objects WHERE lower(name)='{name.lower()}'"
    result = run_query(conn, query)

    return result


def tasks_radius_get(conn, ra: float, decl: float, radius: float, filter: str = "", order: str = "") -> List:
    """
    Returns frames (completed tasks) that are close (within radius degrees) to
    the specified RA/DEC coordinates using proper spherical distance calculation.

    RA must be in degrees (0-360), Dec in degrees (-90 to +90).
    """

    query = """
        SELECT task_id, object, imagename, he_fwhm, ra, decl, comment,
               he_resx, he_resy, filter, he_focal, binning
        FROM tasks
        WHERE state=6 {filter} AND degrees(2 * asin(sqrt(
            pow(sin(radians(decl - {decl}) / 2), 2) +
            cos(radians({decl})) * cos(radians(decl)) *
            pow(sin(radians(ra - {ra}) / 2), 2)
        ))) < {radius}
    """.format(ra=ra, decl=decl, radius=radius, filter=filter)

    if order:
        query += f" ORDER BY {order}"
    result = run_query(conn, query)
    return result


def sensor_get_by_name(conn, name: str) -> dict:
    """
    Retrieves a sensor for a sensor with specified name.
    """
    query = f"SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height FROM sensors WHERE name LIKE '%{name}%'"
    result = run_query(conn, query)

    if len(result) == 0:
        raise ValueError(f"Unable to find sensor '{name}'")
    if len(result) > 1:
        txt = ""
        for s in result:
            txt += f"{s[1]}, "
        raise ValueError(f"More than one sensor matching '{name}': {txt} please be more specific")
    return result[0]
