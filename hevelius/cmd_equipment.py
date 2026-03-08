"""
CLI commands for filters, sensors (cameras), and projects.
"""

from hevelius import db


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


def list_filters(active_only=False):
    """List all filters from the database."""
    cnx = db.connect()
    if active_only:
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE active = true ORDER BY filter_id")
    else:
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters ORDER BY filter_id")
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


def list_projects():
    """List all projects from the database."""
    cnx = db.connect()
    rows = db.run_query(cnx, "SELECT project_id, name, description, ra, decl, active FROM projects ORDER BY project_id")
    cnx.close()
    if not rows:
        print("No projects found.")
        return
    print(f"{'ID':<6} {'Name':<30} {'RA':<10} {'Dec':<10} Active  Description")
    print("-" * 85)
    for r in rows:
        name = (r[1] or "")[:28]
        descr = (r[2] or "")[:32]
        print(f"{r[0]:<6} {name:<30} {r[3]!s:<10} {r[4]!s:<10} {r[5]!s:<6} {descr}")


def show_project(project_id):
    """Show a single project with its subframes and user IDs."""
    cnx = db.connect()
    row = db.run_query(cnx, "SELECT project_id, name, description, ra, decl, active FROM projects WHERE project_id = %s", (project_id,))
    if not row:
        cnx.close()
        print(f"Project {project_id} not found.")
        return 1
    r = row[0]
    print(f"Project ID: {r[0]}")
    print(f"Name:       {r[1]}")
    print(f"Description:{r[2] or ''}")
    print(f"RA:         {r[3]}")
    print(f"Dec:        {r[4]}")
    print(f"Active:     {r[5]}")
    sub = db.run_query(cnx, """SELECT ps.id, f.short_name, ps.exposure_time, ps.count, ps.active
                               FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id
                               WHERE ps.project_id = %s ORDER BY ps.id""", (project_id,))
    print("Subframes:")
    if sub:
        for s in sub:
            count_str = f", count={s[3]}" if s[3] is not None else ""
            print(f"  - filter {s[1]}, exposure {s[2]}s{count_str}, active={s[4]}")
    else:
        print("  (none)")
    users = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
    print("User IDs:", [u[0] for u in (users or [])])
    cnx.close()
    return 0
