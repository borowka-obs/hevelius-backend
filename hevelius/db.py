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


CATALOG_LIST_SORT_FIELDS = {"name", "entries"}
CATALOG_OBJECT_SORT_FIELDS = {"catalog", "name", "ra", "decl", "const", "type", "magn"}

_OBJECT_SELECT = """
    SELECT object_id, name, ra, decl, descr, comment, type, epoch, const,
           magn, x, y, altname, distance, catalog
    FROM objects
"""


def catalogs_installed_list(conn, sort_by: str = "entries", sort_order: str = "desc") -> List:
    """
    Returns installed catalogs with object counts.

    Each row is (name, shortname, object_count).
    sort_by: 'entries' (object count) or 'name'.
    """
    if sort_by not in CATALOG_LIST_SORT_FIELDS:
        sort_by = "entries"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    if sort_by == "name":
        order = f"c.name {sort_order.upper()}"
    else:
        order = f"object_count {sort_order.upper()}, c.name ASC"

    query = f"""
        SELECT LEFT(c.name, 64) AS name, c.shortname, COUNT(o.*) AS object_count
        FROM catalogs c
        LEFT JOIN objects o ON c.shortname = o.catalog
        GROUP BY c.name, c.shortname
        ORDER BY {order}
    """
    return run_query(conn, query)


def catalog_objects_build_where(
    catalog: str = None,
    constellation: str = None,
    name: str = None,
    ra_hours: float = None,
    decl: float = None,
    proximity: float = 1.0,
):
    """
    Build WHERE clause and parameters for catalog object queries.

    Returns (where_suffix, params) where where_suffix is '' or ' WHERE ...'.
    RA is in hours (matching objects.ra storage). Declination is in degrees.
    """
    where_clauses = []
    params = []

    if catalog:
        where_clauses.append("catalog ILIKE %s")
        params.append(catalog)

    if constellation:
        where_clauses.append("const ILIKE %s")
        params.append(constellation)

    if name:
        pattern = f"%{name}%"
        where_clauses.append("(name ILIKE %s OR altname ILIKE %s)")
        params.extend([pattern, pattern])

    if ra_hours is not None and decl is not None:
        ra_deg = ra_hours * 15.0
        where_clauses.append(
            "degrees(2 * asin(sqrt("
            "pow(sin(radians(decl - %s) / 2), 2) + "
            "cos(radians(%s)) * cos(radians(decl)) * "
            "pow(sin(radians(ra*15 - %s) / 2), 2)"
            "))) < %s"
        )
        params.extend([decl, decl, ra_deg, proximity])

    if where_clauses:
        return " WHERE " + " AND ".join(where_clauses), params
    return "", []


def catalog_objects_count(
    conn,
    catalog: str = None,
    constellation: str = None,
    name: str = None,
    ra_hours: float = None,
    decl: float = None,
    proximity: float = 1.0,
) -> int:
    """Return count of objects matching the given filters."""
    where, params = catalog_objects_build_where(
        catalog=catalog,
        constellation=constellation,
        name=name,
        ra_hours=ra_hours,
        decl=decl,
        proximity=proximity,
    )
    query = "SELECT COUNT(*) FROM objects" + where
    return run_query(conn, query, tuple(params) if params else None)[0][0]


def catalog_objects_search(
    conn,
    catalog: str = None,
    constellation: str = None,
    name: str = None,
    ra_hours: float = None,
    decl: float = None,
    proximity: float = 1.0,
    sort_by: str = "name",
    sort_order: str = "asc",
    limit: int = None,
    offset: int = None,
) -> List:
    """
    Search catalog objects with optional filters.

    RA is in hours (matching objects.ra storage). Declination is in degrees.
    When ra_hours and decl are both set, objects within proximity degrees are returned.
    """
    if sort_by not in CATALOG_OBJECT_SORT_FIELDS:
        sort_by = "name"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    where, params = catalog_objects_build_where(
        catalog=catalog,
        constellation=constellation,
        name=name,
        ra_hours=ra_hours,
        decl=decl,
        proximity=proximity,
    )

    query = _OBJECT_SELECT + where
    query += f" ORDER BY {sort_by} {sort_order.upper()}"
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
    if offset is not None:
        query += " OFFSET %s"
        params.append(offset)

    return run_query(conn, query, tuple(params) if params else None)


ASTEROID_SORT_FIELDS = {
    "number", "designation", "name", "absolute_magnitude", "semimajor_axis",
    "eccentricity", "inclination", "mean_motion", "epoch",
}

_ASTEROID_SELECT = """
    SELECT id, number, designation, name, epoch, mean_anomaly, perihelion_arg,
           ascending_node, inclination, eccentricity, mean_motion,
           semimajor_axis, absolute_magnitude, slope_parameter
    FROM asteroids
"""


def asteroids_build_where(
    designation: str = None,
    name: str = None,
    number: int = None,
    numbered: bool = None,
    mag_min: float = None,
    mag_max: float = None,
    tag_names: List[str] = None,
    tags_mode: str = "any",
):
    """
    Build WHERE clause and parameters for asteroid queries.

    Returns (where_suffix, params) where where_suffix is '' or ' WHERE ...'.

    tag_names/tags_mode filter by tag membership: "any" (default) matches
    asteroids carrying at least one of the given tags, "all" requires every
    given tag to be present. Both forms use the asteroid_tag_map(tag_id)
    index via a correlated subquery keyed on asteroid_id, so filtering stays
    cheap even with a large asteroid catalogue.
    """
    where_clauses = []
    params = []

    if designation:
        where_clauses.append("designation ILIKE %s")
        params.append(f"%{designation}%")

    if name:
        where_clauses.append("name ILIKE %s")
        params.append(f"%{name}%")

    if number is not None:
        where_clauses.append("number = %s")
        params.append(number)

    if numbered is not None:
        where_clauses.append("number IS NOT NULL" if numbered else "number IS NULL")

    if mag_min is not None:
        where_clauses.append("absolute_magnitude >= %s")
        params.append(mag_min)

    if mag_max is not None:
        where_clauses.append("absolute_magnitude <= %s")
        params.append(mag_max)

    if tag_names:
        distinct_names = list(dict.fromkeys(tag_names))
        if tags_mode == "all":
            where_clauses.append(
                "(SELECT COUNT(DISTINCT m.tag_id) FROM asteroid_tag_map m "
                "JOIN asteroid_tags t ON t.tag_id = m.tag_id "
                "WHERE m.asteroid_id = asteroids.id AND t.name = ANY(%s)) = %s"
            )
            params.append(distinct_names)
            params.append(len(distinct_names))
        else:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM asteroid_tag_map m "
                "JOIN asteroid_tags t ON t.tag_id = m.tag_id "
                "WHERE m.asteroid_id = asteroids.id AND t.name = ANY(%s))"
            )
            params.append(distinct_names)

    if where_clauses:
        return " WHERE " + " AND ".join(where_clauses), params
    return "", []


def asteroids_count(
    conn,
    designation: str = None,
    name: str = None,
    number: int = None,
    numbered: bool = None,
    mag_min: float = None,
    mag_max: float = None,
    tag_names: List[str] = None,
    tags_mode: str = "any",
) -> int:
    """
    Return count of asteroids matching the given filters.

    NOTE: An unfiltered COUNT(*) scans the full asteroids table. At MPCORB
    scale (~1M+ rows) every default list page pays this cost. Consider caching,
    approximate counts, or requiring a filter if this becomes a bottleneck.
    """
    where, params = asteroids_build_where(
        designation=designation, name=name, number=number, numbered=numbered,
        mag_min=mag_min, mag_max=mag_max, tag_names=tag_names, tags_mode=tags_mode,
    )
    query = "SELECT COUNT(*) FROM asteroids" + where
    return run_query(conn, query, tuple(params) if params else None)[0][0]


def asteroids_search(
    conn,
    designation: str = None,
    name: str = None,
    number: int = None,
    numbered: bool = None,
    mag_min: float = None,
    mag_max: float = None,
    tag_names: List[str] = None,
    tags_mode: str = "any",
    sort_by: str = "number",
    sort_order: str = "asc",
    limit: int = None,
    offset: int = None,
) -> List:
    """Search asteroids with optional filters, sorting, and paging."""
    if sort_by not in ASTEROID_SORT_FIELDS:
        sort_by = "number"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    where, params = asteroids_build_where(
        designation=designation, name=name, number=number, numbered=numbered,
        mag_min=mag_min, mag_max=mag_max, tag_names=tag_names, tags_mode=tags_mode,
    )

    query = _ASTEROID_SELECT + where
    query += f" ORDER BY {sort_by} {sort_order.upper()} NULLS LAST, id ASC"
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
    if offset is not None:
        query += " OFFSET %s"
        params.append(offset)

    return run_query(conn, query, tuple(params) if params else None)


def asteroid_get_by_id(conn, asteroid_id: int):
    """Return a single asteroid row by its primary key, or None if not found."""
    rows = run_query(conn, _ASTEROID_SELECT + " WHERE id = %s", (asteroid_id,))
    return rows[0] if rows else None


def asteroids_find_by_query(conn, query: str, limit: int = 20) -> List:
    """
    Resolve a user query (name, designation, or MPC number) to asteroid rows.

    Preference order:
      1. Exact MPC number (when query is an integer)
      2. Exact case-insensitive proper name
      3. Exact case-insensitive packed designation
      4. Partial name / designation matches (ILIKE)
    """
    q = (query or "").strip()
    if not q:
        return []

    if q.isdigit():
        rows = run_query(
            conn,
            _ASTEROID_SELECT + " WHERE number = %s ORDER BY id ASC LIMIT %s",
            (int(q), limit),
        )
        if rows:
            return rows

    exact_name = run_query(
        conn,
        _ASTEROID_SELECT + " WHERE lower(name) = lower(%s) ORDER BY number NULLS LAST, id ASC LIMIT %s",
        (q, limit),
    )
    if exact_name:
        return exact_name

    exact_desig = run_query(
        conn,
        _ASTEROID_SELECT
        + " WHERE lower(designation) = lower(%s) ORDER BY number NULLS LAST, id ASC LIMIT %s",
        (q, limit),
    )
    if exact_desig:
        return exact_desig

    return run_query(
        conn,
        _ASTEROID_SELECT
        + " WHERE name ILIKE %s OR designation ILIKE %s"
        + " ORDER BY number NULLS LAST, id ASC LIMIT %s",
        (f"%{q}%", f"%{q}%", limit),
    )


def telescope_resolve(conn, scope_id: int = None, name: str = None):
    """
    Resolve a telescope by scope_id and/or name.

    Returns (scope_id, name, lat, lon, alt) or raises ValueError with a
    user-facing message when the telescope cannot be uniquely resolved or
    has no GPS coordinates.
    """
    if scope_id is None and not name:
        raise ValueError("Specify --telescope-id or --telescope.")

    if scope_id is not None:
        rows = run_query(
            conn,
            "SELECT scope_id, name, lat, lon, alt FROM telescopes WHERE scope_id = %s",
            (scope_id,),
        )
        if not rows:
            raise ValueError(f"Telescope scope_id={scope_id} not found.")
        row = rows[0]
        if name and row[1] and row[1].lower() != name.strip().lower():
            raise ValueError(
                f"Telescope scope_id={scope_id} is named {row[1]!r}, "
                f"not {name.strip()!r}."
            )
    else:
        q = name.strip()
        rows = run_query(
            conn,
            "SELECT scope_id, name, lat, lon, alt FROM telescopes "
            "WHERE lower(name) = lower(%s) ORDER BY scope_id",
            (q,),
        )
        if not rows:
            rows = run_query(
                conn,
                "SELECT scope_id, name, lat, lon, alt FROM telescopes "
                "WHERE name ILIKE %s ORDER BY scope_id LIMIT 10",
                (f"%{q}%",),
            )
        if not rows:
            raise ValueError(f"No telescope matching name {q!r}.")
        if len(rows) > 1:
            listing = ", ".join(f"{r[0]}:{r[1]}" for r in rows)
            raise ValueError(
                f"Multiple telescopes match {q!r} ({listing}). "
                "Use --telescope-id for an exact match."
            )
        row = rows[0]

    sid, tname, lat, lon, alt = row
    if lat is None or lon is None:
        raise ValueError(
            f"Telescope {tname or sid} (scope_id={sid}) has no lat/lon configured."
        )
    return sid, tname, float(lat), float(lon), float(alt or 0.0)


def asteroid_tags_for_asteroids(conn, asteroid_ids: List[int]) -> dict:
    """
    Batch-fetch tags for multiple asteroids in a single query (avoids N+1
    lookups when building a paginated asteroid list).

    Returns {asteroid_id: [{"tag_id", "name", "description", "color"}, ...]},
    with every requested id present (empty list if untagged).
    """
    result = {aid: [] for aid in asteroid_ids}
    if not asteroid_ids:
        return result
    rows = run_query(
        conn,
        """
        SELECT m.asteroid_id, t.tag_id, t.name, t.description, t.color
        FROM asteroid_tag_map m
        JOIN asteroid_tags t ON t.tag_id = m.tag_id
        WHERE m.asteroid_id = ANY(%s)
        ORDER BY t.name
        """,
        (list(asteroid_ids),),
    )
    for asteroid_id, tag_id, name, description, color in rows or []:
        result[asteroid_id].append({
            "tag_id": tag_id, "name": name, "description": description, "color": color,
        })
    return result


def asteroid_tag_attach(conn, asteroid_id: int, tag_id: int) -> None:
    """Attach a tag to an asteroid; a no-op if already attached."""
    run_query(
        conn,
        "INSERT INTO asteroid_tag_map (asteroid_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (asteroid_id, tag_id),
    )


def asteroid_tag_detach(conn, asteroid_id: int, tag_id: int) -> None:
    """Detach a tag from an asteroid; a no-op if not attached."""
    run_query(
        conn,
        "DELETE FROM asteroid_tag_map WHERE asteroid_id = %s AND tag_id = %s",
        (asteroid_id, tag_id),
    )


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
