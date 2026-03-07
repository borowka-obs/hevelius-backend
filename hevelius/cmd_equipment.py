"""
CLI commands for filters, sensors (cameras), and projects.
"""

from hevelius import db


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


def list_sensors(active_only=False):
    """List all sensors (cameras) from the database."""
    cnx = db.connect()
    if active_only:
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                                   FROM sensors WHERE active = true ORDER BY sensor_id""")
    else:
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                                   FROM sensors ORDER BY sensor_id""")
    cnx.close()
    if not rows:
        print("No sensors found.")
        return
    print(f"{'ID':<6} {'Name':<28} {'Res':<12} {'Pixel(µm)':<14} bits  {'Size(mm)':<14} vendor/url active")
    print("-" * 100)
    for r in rows:
        res = f"{r[2]}x{r[3]}"
        px = f"{r[4]}x{r[5]}"
        size = f"{r[7]}x{r[8]}"
        vendor = (r[9] or "")[:12]
        print(f"{r[0]:<6} {(r[1] or '')[:26]:<28} {res:<12} {px:<14} {r[6]:<4} {size:<14} {vendor:<12} {r[11]}")


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
