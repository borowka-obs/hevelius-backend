"""
CLI commands for filters, sensors (cameras), and projects.
"""

from hevelius import db


def get_filter_id_by_short_name(short_name):
    """Look up filter_id by filter short_name. Returns filter_id (int) or None if not found."""
    if not short_name or not str(short_name).strip():
        return None
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT filter_id FROM filters WHERE short_name = %s", (str(short_name).strip(),))
    cnx.close()
    return row[0][0] if row else None


def add_filter(short_name, full_name=None, url=None, active=True):
    """Add a new filter. Returns filter_id on success, None on error."""
    cnx = db.connect()
    try:
        row = db.run_query(
            cnx,
            "INSERT INTO filters (short_name, full_name, url, active) VALUES (%s, %s, %s, %s) RETURNING filter_id",
            (short_name, full_name, url, active)
        )
    except Exception as e:
        cnx.close()
        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
            print(f"Error: A filter with short_name '{short_name}' already exists.")
        else:
            print(f"Error: {e}")
        return None
    filter_id = row if isinstance(row, int) else (row[0] if row else None)
    cnx.close()
    if filter_id is None:
        print("Error: Failed to create filter.")
        return None
    print(f"Created filter id={filter_id} short_name={short_name}")
    return filter_id


def edit_filter(filter_id, short_name=None, full_name=None, url=None, active=None):
    """Update an existing filter. Returns True on success."""
    cnx = db.connect()
    rows = db.run_query(cnx, "SELECT filter_id FROM filters WHERE filter_id = %s", (filter_id,))
    if not rows:
        cnx.close()
        print(f"Filter id={filter_id} not found.")
        return False
    updates = []
    params = []
    if short_name is not None:
        updates.append("short_name = %s")
        params.append(short_name)
    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name)
    if url is not None:
        updates.append("url = %s")
        params.append(url)
    if active is not None:
        updates.append("active = %s")
        params.append(active)
    if not updates:
        cnx.close()
        print("No changes specified.")
        return False
    try:
        params.append(filter_id)
        db.run_query(cnx, "UPDATE filters SET " + ", ".join(updates) + " WHERE filter_id = %s", tuple(params))
    except Exception as e:
        cnx.close()
        if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
            print("Error: A filter with that short_name already exists.")
        else:
            print(f"Error: {e}")
        return False
    cnx.close()
    print(f"Updated filter id={filter_id}.")
    return True


def set_filter_active(filter_id, active):
    """Set filter active flag. Returns True on success."""
    cnx = db.connect()
    rows = db.run_query(cnx, "SELECT filter_id FROM filters WHERE filter_id = %s", (filter_id,))
    if not rows:
        cnx.close()
        print(f"Filter id={filter_id} not found.")
        return False
    db.run_query(cnx, "UPDATE filters SET active = %s WHERE filter_id = %s", (active, filter_id))
    cnx.close()
    status = "active" if active else "inactive"
    print(f"Filter id={filter_id} is now {status}.")
    return True


FILTER_SORT_FIELDS = {"filter_id", "short_name", "full_name", "active"}


def list_filters(active_only=False, sort_by="filter_id", sort_order="asc"):
    """List all filters from the database. Sortable by filter_id, short_name, full_name, active."""
    if sort_by not in FILTER_SORT_FIELDS:
        sort_by = "filter_id"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"
    order = f"ORDER BY {sort_by} {sort_order}"
    cnx = db.connect()
    if active_only:
        rows = db.run_query(cnx, f"SELECT filter_id, short_name, full_name, url, active FROM filters WHERE active = true {order}")
    else:
        rows = db.run_query(cnx, f"SELECT filter_id, short_name, full_name, url, active FROM filters {order}")
    cnx.close()
    if not rows:
        print("No filters found.")
        return
    print(f"{'ID':<6} {'Short':<8} {'Full name':<24} {'URL':<20} Active")
    print("-" * 70)
    for r in rows:
        url = (r[3] or "")[:18] + ".." if r[3] and len(r[3]) > 20 else (r[3] or "")
        print(f"{r[0]:<6} {r[1]:<8} {(r[2] or '')[:22]:<24} {url:<20} {r[4]}")


SENSOR_SORT_FIELDS = {"sensor_id", "name", "resx", "resy", "pixel_x", "pixel_y", "width", "height", "vendor"}


def add_sensor(name, resx=None, resy=None, pixel_x=None, pixel_y=None, bits=None, width=None, height=None,
               vendor=None, url=None, active=True):
    """Add a new sensor. resx, resy, pixel_x, pixel_y are required. width/height are computed if not given.
    bits defaults to 0. Returns sensor_id on success, None on error."""
    if resx is None or resy is None or pixel_x is None or pixel_y is None:
        print("Error: resx, resy, pixel_x and pixel_y are required (use --resx, --resy, --pixel-x, --pixel-y).")
        return None
    if width is None:
        width = round(resx * pixel_x / 1000.0, 2)
    if height is None:
        height = round(resy * pixel_y / 1000.0, 2)
    if width is not None:
        width = round(width, 2)
    if height is not None:
        height = round(height, 2)
    if bits is None:
        bits = 0
    cnx = db.connect()
    try:
        row = db.run_query(
            cnx,
            """INSERT INTO sensors (name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING sensor_id""",
            (name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active)
        )
    except Exception as e:
        cnx.close()
        print(f"Error: {e}")
        return None
    sensor_id = row if isinstance(row, int) else (row[0] if row else None)
    cnx.close()
    if sensor_id is None:
        print("Error: Failed to create sensor.")
        return None
    print(f"Created sensor id={sensor_id} name={name}")
    return sensor_id


def edit_sensor(sensor_id, name=None, resx=None, resy=None, pixel_x=None, pixel_y=None, bits=None,
                width=None, height=None, vendor=None, url=None, active=None):
    """Update an existing sensor. Returns True on success."""
    cnx = db.connect()
    rows = db.run_query(cnx, "SELECT sensor_id FROM sensors WHERE sensor_id = %s", (sensor_id,))
    if not rows:
        cnx.close()
        print(f"Sensor id={sensor_id} not found.")
        return False
    updates = []
    params = []
    for key, val in [
        ("name", name), ("resx", resx), ("resy", resy), ("pixel_x", pixel_x), ("pixel_y", pixel_y),
        ("bits", bits), ("width", round(width, 2) if width is not None else None),
        ("height", round(height, 2) if height is not None else None),
        ("vendor", vendor), ("url", url), ("active", active)
    ]:
        if val is not None:
            updates.append(f"{key} = %s")
            params.append(val)
    if not updates:
        cnx.close()
        print("No changes specified.")
        return False
    params.append(sensor_id)
    try:
        db.run_query(cnx, "UPDATE sensors SET " + ", ".join(updates) + " WHERE sensor_id = %s", tuple(params))
    except Exception as e:
        cnx.close()
        print(f"Error: {e}")
        return False
    cnx.close()
    print(f"Updated sensor id={sensor_id}.")
    return True


def list_sensors(active_only=False, sort_by="sensor_id", sort_order="asc"):
    """List all sensors (cameras) from the database."""
    if sort_by not in SENSOR_SORT_FIELDS:
        sort_by = "sensor_id"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"
    order = f"ORDER BY {sort_by} {sort_order}"
    cnx = db.connect()
    if active_only:
        rows = db.run_query(cnx, f"""SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                                   FROM sensors WHERE active = true {order}""")
    else:
        rows = db.run_query(cnx, f"""SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                                   FROM sensors {order}""")
    cnx.close()
    if not rows:
        print("No sensors found.")
        return
    print(f"{'ID':<6} {'Name':<28} {'Res':<12} {'Pixel(µm)':<14} bits  {'Size(mm)':<14} vendor/url active")
    print("-" * 100)
    for r in rows:
        res = f"{r[2] or 0}x{r[3] or 0}"
        px = f"{r[4] or 0}x{r[5] or 0}"
        w = round((r[7] or 0), 2)
        h = round((r[8] or 0), 2)
        size = f"{w:.2f}x{h:.2f}"
        bits_val = r[6] if r[6] is not None else 0
        vendor = (r[9] or "")[:12]
        active_val = r[11] if r[11] is not None else False
        print(f"{r[0]:<6} {(r[1] or '')[:26]:<28} {res:<12} {px:<14} {bits_val:<4} {size:<14} {vendor:<12} {active_val}")


def list_projects(scope_id=None):
    """List all projects from the database. If scope_id is set, only projects for that telescope."""
    cnx = db.connect()
    if scope_id is not None:
        rows = db.run_query(cnx, "SELECT project_id, name, description, scope_id, ra, decl, active FROM projects WHERE scope_id = %s ORDER BY project_id",
                            (scope_id,))
    else:
        rows = db.run_query(cnx, "SELECT project_id, name, description, scope_id, ra, decl, active FROM projects ORDER BY project_id")
    cnx.close()
    if not rows:
        print("No projects found.")
        return
    print(f"{'ID':<6} {'Name':<30} {'Scope':<6} {'RA':<10} {'Dec':<10} Active  Description")
    print("-" * 95)
    for r in rows:
        name = (r[1] or "")[:28]
        descr = (r[2] or "")[:32]
        print(f"{r[0]:<6} {name:<30} {r[3]:<6} {r[4]!s:<10} {r[5]!s:<10} {r[6]!s:<6} {descr}")


def show_project(project_id):
    """Show a single project with its subframes and user IDs."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT project_id, name, description, scope_id, ra, decl, active FROM projects WHERE project_id = %s", (project_id,))
    if not row:
        cnx.close()
        print(f"Project {project_id} not found.")
        return 1
    r = row[0]
    print(f"Project ID: {r[0]}")
    print(f"Name:       {r[1]}")
    print(f"Description:{r[2] or ''}")
    print(f"Scope ID:   {r[3]}")
    print(f"RA:         {r[4]}")
    print(f"Dec:        {r[5]}")
    print(f"Active:     {r[6]}")
    sub = db.run_query(cnx, """SELECT ps.id, f.short_name, ps.exposure_time, ps.goal_count, ps.active
                               FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id
                               WHERE ps.project_id = %s ORDER BY ps.id""", (project_id,))
    print("Subframes:")
    if sub:
        for s in sub:
            goal_str = f", goal_count={s[3]}" if s[3] is not None else ""
            print(f"  - id={s[0]} filter {s[1]}, exposure {s[2]}s{goal_str}, active={s[4]}")
    else:
        print("  (none)")
    users = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
    print("User IDs:", [u[0] for u in (users or [])])
    cnx.close()
    return 0


def add_project(name, scope_id, description=None, ra=None, dec=None, active=True):
    """Add a new project. name and scope_id required. If ra/dec not given, resolve from catalog by name. Returns project_id or None on failure."""
    cnx = db.connect()
    if ra is None or dec is None:
        cat = db.run_query(cnx, "SELECT object_id, name, ra, decl FROM objects WHERE lower(name)=%s", (name.strip().lower(),))
        if not cat:
            cnx.close()
            return None
        ra, dec = cat[0][2], cat[0][3]
    scope_exists = db.run_query(cnx, "SELECT 1 FROM telescopes WHERE scope_id = %s", (scope_id,))
    if not scope_exists:
        cnx.close()
        return None
    db.run_query(cnx, "INSERT INTO projects (name, description, scope_id, ra, decl, active) VALUES (%s, %s, %s, %s, %s, %s)",
                 (name, description or "", scope_id, ra, dec, active))
    row = db.run_query(cnx, "SELECT project_id FROM projects WHERE name=%s AND scope_id=%s ORDER BY project_id DESC LIMIT 1", (name, scope_id))
    project_id = row[0][0]
    cnx.close()
    return project_id


def edit_project(project_id, name=None, description=None, scope_id=None, ra=None, dec=None, active=None):
    """Update project fields. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
    if not row:
        cnx.close()
        return False
    updates = []
    args = []
    for key, val in (("name", name), ("description", description), ("scope_id", scope_id), ("ra", ra), ("decl", dec), ("active", active)):
        if val is not None:
            updates.append(f"{key} = %s")
            args.append(val)
    if not updates:
        cnx.close()
        return True
    args.append(project_id)
    db.run_query(cnx, "UPDATE projects SET " + ", ".join(updates) + " WHERE project_id = %s", tuple(args))
    cnx.close()
    return True


def add_project_subframe(project_id, filter_id, exposure_time, goal_count=None, active=True):
    """Add a subframe to a project. Returns subframe id or None."""
    cnx = db.connect()
    try:
        proj = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
        if not proj:
            return None
        subframe_id = db.run_query(
            cnx,
            "INSERT INTO project_subframes (project_id, filter_id, exposure_time, goal_count, active) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (project_id, filter_id, exposure_time, goal_count, active),
        )
        if subframe_id is None:
            return None
        cnx.commit()
        return subframe_id
    finally:
        cnx.close()


def edit_project_subframe(project_id, subframe_id, filter_id=None, exposure_time=None, goal_count=None, active=None):
    """Update a subframe. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT id FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
    if not row:
        cnx.close()
        return False
    updates = []
    args = []
    for key, val in (("filter_id", filter_id), ("exposure_time", exposure_time), ("goal_count", goal_count), ("active", active)):
        if val is not None:
            updates.append(f"{key} = %s")
            args.append(val)
    if not updates:
        cnx.close()
        return True
    args.extend([project_id, subframe_id])
    db.run_query(cnx, "UPDATE project_subframes SET " + ", ".join(updates) + " WHERE project_id = %s AND id = %s", tuple(args))
    cnx.close()
    return True


def remove_project_subframe(project_id, subframe_id):
    """Remove a subframe from a project. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT id FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
    if not row:
        cnx.close()
        return False
    db.run_query(cnx, "DELETE FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
    cnx.close()
    return True


# Task state 6 = DONE (complete)
TASK_STATE_DONE = 6


def project_stats(project_id):
    """Print task statistics for a project (total, incomplete, done). Returns 0 on success."""
    cnx = db.connect()
    proj = db.run_query(cnx, "SELECT project_id, name FROM projects WHERE project_id = %s", (project_id,))
    if not proj:
        cnx.close()
        print(f"Project {project_id} not found.")
        return 1
    total = db.run_query(cnx, "SELECT COUNT(*) FROM task_projects WHERE project_id = %s", (project_id,))[0][0]
    incomplete = db.run_query(cnx, """SELECT COUNT(*) FROM task_projects tp JOIN tasks t ON tp.task_id = t.task_id
        WHERE tp.project_id = %s AND t.state != %s""", (project_id, TASK_STATE_DONE))[0][0]
    done = db.run_query(cnx, """SELECT COUNT(*) FROM task_projects tp JOIN tasks t ON tp.task_id = t.task_id
        WHERE tp.project_id = %s AND t.state = %s""", (project_id, TASK_STATE_DONE))[0][0]
    cnx.close()
    print(f"Project {project_id} ({proj[0][1]}): total_tasks={total}, tasks_incomplete={incomplete}, tasks_done={done}")
    return 0


def add_task_to_project(project_id, task_id):
    """Assign a task to a project. Returns True on success."""
    cnx = db.connect()
    task_row = db.run_query(cnx, "SELECT task_id FROM tasks WHERE task_id = %s", (task_id,))
    if not task_row:
        cnx.close()
        print(f"Task {task_id} not found.")
        return False
    proj = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
    if not proj:
        cnx.close()
        print(f"Project {project_id} not found.")
        return False
    db.run_query(cnx, "INSERT INTO task_projects (task_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (task_id, project_id))
    cnx.close()
    return True


def remove_task_from_project(project_id, task_id):
    """Remove a task from a project. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT 1 FROM task_projects WHERE task_id = %s AND project_id = %s", (task_id, project_id))
    if not row:
        cnx.close()
        print(f"Task {task_id} is not assigned to project {project_id}.")
        return False
    db.run_query(cnx, "DELETE FROM task_projects WHERE task_id = %s AND project_id = %s", (task_id, project_id))
    cnx.close()
    return True


# --- Telescopes ---

SCOPE_SORT_FIELDS = {"scope_id", "name", "focal", "active"}


def list_telescopes(sort_by="scope_id", sort_order="asc"):
    """List all telescopes with optional sorting (scope_id, name, focal, active)."""
    if sort_by not in SCOPE_SORT_FIELDS:
        sort_by = "scope_id"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"
    order = f"ORDER BY t.{sort_by} {sort_order}"
    cnx = db.connect()
    rows = db.run_query(cnx, f"""
        SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
               t.lon, t.lat, t.alt, t.sensor_id, t.active,
               s.name AS sensor_name
        FROM telescopes t
        LEFT JOIN sensors s ON t.sensor_id = s.sensor_id
        {order}
    """)
    cnx.close()
    if not rows:
        print("No telescopes found.")
        return
    print(f"{'ID':<6} {'Name':<24} {'Focal':<8} {'Sensor':<22} Active")
    print("-" * 75)
    for r in rows:
        name = (r[1] or "")[:22]
        focal = r[5] if r[5] is not None else ""
        sensor = (r[12] or "")[:20] if len(r) > 12 else ""
        print(f"{r[0]:<6} {name:<24} {focal!s:<8} {sensor:<22} {r[11]}")


def add_telescope(name, scope_id=None, descr=None, min_dec=None, max_dec=None, focal=None, aperture=None,
                  lon=None, lat=None, alt=None, sensor_id=None, active=True):
    """Add a new telescope. scope_id is optional (auto-assigned if omitted). Returns scope_id on success, None on failure."""
    if sensor_id == 0:
        sensor_id = None
    cnx = db.connect()
    if scope_id is None:
        row = db.run_query(cnx, "SELECT COALESCE(MAX(scope_id), 0) + 1 FROM telescopes")
        scope_id = row[0][0] if row else 1
    else:
        existing = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
        if existing:
            cnx.close()
            print(f"Error: Telescope scope_id={scope_id} already exists.")
            return None
    cols = ["scope_id", "name"]
    vals = [scope_id, name]
    for key, val in [
        ("descr", descr), ("min_dec", min_dec), ("max_dec", max_dec), ("focal", focal),
        ("aperture", aperture), ("lon", lon), ("lat", lat), ("alt", alt), ("active", active)
    ]:
        if val is not None:
            cols.append(key)
            vals.append(val)
    if sensor_id is not None:
        cols.append("sensor_id")
        vals.append(sensor_id)
    placeholders = ", ".join(["%s"] * len(vals))
    try:
        db.run_query(cnx, f"INSERT INTO telescopes ({', '.join(cols)}) VALUES ({placeholders})", vals)
    except Exception as e:
        cnx.close()
        print(f"Error: {e}")
        return None
    cnx.close()
    print(f"Created telescope scope_id={scope_id} name={name}")
    return scope_id


def edit_telescope(scope_id, name=None, descr=None, min_dec=None, max_dec=None, focal=None, aperture=None,
                   lon=None, lat=None, alt=None, sensor_id=None, active=None):
    """Edit an existing telescope. sensor_id=0 removes the sensor. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
    if not row:
        cnx.close()
        print(f"Telescope scope_id={scope_id} not found.")
        return False
    updates = []
    params = []
    for key, val in [
        ("name", name), ("descr", descr), ("min_dec", min_dec), ("max_dec", max_dec),
        ("focal", focal), ("aperture", aperture), ("lon", lon), ("lat", lat), ("alt", alt), ("active", active)
    ]:
        if val is not None:
            updates.append(f"{key} = %s")
            params.append(val)
    if sensor_id is not None:
        updates.append("sensor_id = %s")
        params.append(None if sensor_id == 0 else sensor_id)
    if not updates:
        cnx.close()
        print("No changes specified.")
        return False
    params.append(scope_id)
    db.run_query(cnx, "UPDATE telescopes SET " + ", ".join(updates) + " WHERE scope_id = %s", tuple(params))
    cnx.close()
    print(f"Updated telescope scope_id={scope_id}.")
    return True


def show_telescope(scope_id):
    """Show telescope details including sensor and filters. Returns 0 on success, 1 if not found."""
    cnx = db.connect()
    row = db.run_query(cnx, """
        SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
               t.lon, t.lat, t.alt, t.sensor_id, t.active
        FROM telescopes t WHERE t.scope_id = %s
    """, (scope_id,))
    if not row:
        cnx.close()
        print(f"Telescope scope_id={scope_id} not found.")
        return 1
    r = row[0]
    print(f"Scope ID:  {r[0]}")
    print(f"Name:      {r[1]}")
    print(f"Descr:     {r[2] or ''}")
    print(f"Min dec:   {r[3]}")
    print(f"Max dec:   {r[4]}")
    print(f"Focal:     {r[5]}")
    print(f"Aperture:  {r[6]}")
    print(f"Lon/Lat/Alt: {r[7]} / {r[8]} / {r[9]}")
    print(f"Active:    {r[11]}")
    if r[10] is not None:
        srow = db.run_query(cnx, """
            SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
            FROM sensors WHERE sensor_id = %s
        """, (r[10],))
        if srow:
            s = srow[0]
            print("Sensor (camera):")
            print(f"  sensor_id={s[0]} name={s[1]} res={s[2]}x{s[3]} pixel={s[4]}x{s[5]} µm bits={s[6]}")
            print(f"  size={s[7]}x{s[8]} mm vendor={s[9]} url={s[10]} active={s[11]}")
    else:
        print("Sensor: (none)")
    filters = db.run_query(cnx, """
        SELECT f.filter_id, f.short_name, f.full_name, f.url, f.active
        FROM telescope_filters tf JOIN filters f ON tf.filter_id = f.filter_id
        WHERE tf.scope_id = %s ORDER BY f.filter_id
    """, (scope_id,))
    print("Filters:")
    if filters:
        for f in filters:
            print(f"  filter_id={f[0]} short_name={f[1]} full_name={f[2]} active={f[4]}")
    else:
        print("  (none)")
    cnx.close()
    return 0


def set_telescope_sensor(scope_id, sensor_id):
    """Set or clear the telescope's sensor. sensor_id=0 removes the sensor. Returns True on success."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
    if not row:
        cnx.close()
        print(f"Telescope scope_id={scope_id} not found.")
        return False
    sid = None if sensor_id == 0 else sensor_id
    if sid is not None:
        srow = db.run_query(cnx, "SELECT sensor_id FROM sensors WHERE sensor_id = %s", (sid,))
        if not srow:
            cnx.close()
            print(f"Sensor id={sensor_id} not found.")
            return False
    db.run_query(cnx, "UPDATE telescopes SET sensor_id = %s WHERE scope_id = %s", (sid, scope_id))
    cnx.close()
    if sid is None:
        print(f"Removed sensor from telescope scope_id={scope_id}.")
    else:
        print(f"Set telescope scope_id={scope_id} sensor_id={sensor_id}.")
    return True


def add_telescope_filter(scope_id, filter_id):
    """Add a filter to a telescope. Returns True on success."""
    cnx = db.connect()
    scope = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
    flt = db.run_query(cnx, "SELECT filter_id FROM filters WHERE filter_id = %s", (filter_id,))
    if not scope or not flt:
        cnx.close()
        print("Telescope or filter not found.")
        return False
    try:
        db.run_query(cnx, "INSERT INTO telescope_filters (scope_id, filter_id) VALUES (%s, %s)", (scope_id, filter_id))
    except Exception as e:
        cnx.close()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            print("Filter is already assigned to this telescope.")
        else:
            print(f"Error: {e}")
        return False
    cnx.close()
    print(f"Added filter_id={filter_id} to telescope scope_id={scope_id}.")
    return True


def remove_telescope_filter(scope_id, filter_id):
    """Remove a filter from a telescope. Returns True on success."""
    cnx = db.connect()
    db.run_query(cnx, "DELETE FROM telescope_filters WHERE scope_id = %s AND filter_id = %s", (scope_id, filter_id))
    cnx.close()
    print(f"Removed filter_id={filter_id} from telescope scope_id={scope_id}.")
    return True
