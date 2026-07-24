import sys

import numpy as np
import pandas as pd
import plotly.express as px

from hevelius import db
from hevelius.utils import deg2rah, format_dec, format_ra


# ANSI foreground codes for catalog labels (stable per shortname).
_CATALOG_ANSI = {
    "NGC": "91",   # bright red
    "IC": "94",    # bright blue
    "M": "93",     # bright yellow
    "C": "95",     # bright magenta
    "Ced": "96",   # bright cyan
    "LBN": "92",   # bright green
    "LDN": "32",   # green
    "Sh2": "35",   # magenta
    "B": "33",     # yellow
    "Cr": "36",    # cyan
    "Mel": "31",   # red
    "Gum": "34",   # blue
    "RCW": "95",
    "vdB": "96",
}
_FALLBACK_ANSI = ["31", "32", "33", "34", "35", "36", "91", "92", "93", "94", "95", "96"]


def stats():
    """
    Prints database statistics (version, overall, by state, by user)

    :param args: arguments parsed by argparse
    """

    cnx = db.connect()

    ver = db.version_get(cnx)

    print(f"Schema version is {ver}")

    if ver == 0:
        print("DB not initialized (schema version is 0), can't show any stats")
        return

    db.stats_print(cnx)

    print("\nStats by state:")
    by_state = db.stats_by_state(cnx)
    for state_id, name, cnt in by_state:
        print(f"{name:>18}({state_id:2}): {cnt}")

    print("\nStats by user:")
    by_user = db.stats_by_user(cnx)
    for name, user_id, cnt in by_user:
        print(f"{name:>18}({user_id:2}): {cnt}")

    cnx.close()


def histogram(args=None):
    """
    Generates frequency of photo frames for the whole sky.
    Buckets are 1x1 degree. Returns a numpy array of shape (180, 360)
    where row 0 is decl +90° and column 0 is RA 0°.
    """
    return np.array(sky_histogram_grid()[0], dtype=float)


def sky_histogram_grid(conn=None):
    """
    Build a 1°×1° sky density grid for completed plate-solved tasks.

    Returns (grid, total_frames) where grid is a list of 180 rows × 360 cols
    (ints). Row i corresponds to declination (90 - i) degrees; column j is RA j°.
    """
    close = False
    if conn is None:
        conn = db.connect()
        close = True
    try:
        rows = db.run_query(
            conn,
            """SELECT he_solved_ra, he_solved_dec FROM tasks
               WHERE imagename IS NOT NULL
                 AND he_solved_ra IS NOT NULL
                 AND state = 6""",
        )
    finally:
        if close:
            conn.close()

    grid = [[0] * 360 for _ in range(180)]
    total = 0
    for ra_f, decl_f in rows or []:
        try:
            ra = int(ra_f)
            decl = int(decl_f)
        except (TypeError, ValueError):
            continue
        if ra < 0 or ra >= 360:
            continue
        row = 90 - decl
        if row < 0 or row >= 180:
            continue
        grid[row][ra] += 1
        total += 1
    return grid, total


def sky_histogram_payload(conn=None):
    """JSON-serialisable sparse sky histogram for the REST API."""
    grid, total = sky_histogram_grid(conn)
    cells = []
    for row_idx, row in enumerate(grid):
        decl_deg = 90 - row_idx
        for ra_deg, count in enumerate(row):
            if count:
                cells.append({
                    "ra_deg": ra_deg,
                    "decl_deg": decl_deg,
                    "count": int(count),
                })
    return {
        "resolution_deg": 1,
        "ra_bins": 360,
        "decl_bins": 180,
        "ra_unit": "deg",
        "total_frames": int(total),
        "nonempty_cells": len(cells),
        "cells": cells,
    }


def _ansi(code: str, text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _catalog_ansi(catalog) -> str:
    if not catalog:
        return "2"  # dim
    key = str(catalog).strip()
    mapped = _CATALOG_ANSI.get(key)
    if mapped:
        return mapped
    for known, code in _CATALOG_ANSI.items():
        if known.lower() == key.lower():
            return code
    return _FALLBACK_ANSI[sum(ord(c) for c in key) % len(_FALLBACK_ANSI)]


def _fmt_dec_signed(decl: float) -> str:
    text = format_dec(decl)
    if text.startswith("-"):
        return text
    return f"+{text}"


def _format_object_names(objects, color: bool) -> tuple:
    """Return (colored_names, plain_names) for a catalog_radius_get result."""
    plain_parts = []
    colored_parts = []
    for obj in objects:
        name = obj[1]
        catalog = obj[5] if len(obj) > 5 else None
        plain_parts.append(name)
        colored_parts.append(_ansi(_catalog_ansi(catalog), name, color))
    return " ".join(colored_parts), " ".join(plain_parts)


def groups(args):
    histo = histogram(args)

    min_frames = args.min
    print(f"Showing groups with more than {min_frames} frame(s)")
    poi = []
    for decl in range(0, 180):
        for ra in range(0, 360):
            if histo[decl][ra] > min_frames:
                actual_decl = 90 - decl
                actual_ra = ra / 15
                poi.append(
                    {"cnt": int(histo[decl][ra]), "ra": actual_ra, "decl": actual_decl})

    poi = sorted(poi, key=lambda p: p['cnt'], reverse=True)

    conn = db.connect()
    color = sys.stdout.isatty()
    rows = []

    for p in poi:
        ra = p['ra']
        decl = p['decl']
        objects = db.catalog_radius_get(conn, ra, decl, 1.0)
        tasks = db.tasks_radius_get(conn, ra, decl, 1.0)
        names_colored, _names_plain = _format_object_names(objects, color)
        rows.append({
            "frames": p["cnt"],
            "ra": format_ra(ra),
            "dec": _fmt_dec_signed(decl),
            "obj": len(objects),
            "tasks": len(tasks),
            "names": names_colored,
        })

    conn.close()

    if not rows:
        print("No groups found.")
        return

    w_frames = max(len("Frames"), max(len(str(r["frames"])) for r in rows))
    w_ra = max(len("RA"), max(len(r["ra"]) for r in rows))
    w_dec = max(len("Dec"), max(len(r["dec"]) for r in rows))
    w_obj = max(len("Obj"), max(len(str(r["obj"])) for r in rows))
    w_tasks = max(len("Tasks"), max(len(str(r["tasks"])) for r in rows))

    header = (
        f"{'Frames':>{w_frames}}  {'RA':<{w_ra}}  {'Dec':<{w_dec}}  "
        f"{'Obj':>{w_obj}}  {'Tasks':>{w_tasks}}  Objects"
    )
    rule = (
        f"{'-' * w_frames}  {'-' * w_ra}  {'-' * w_dec}  "
        f"{'-' * w_obj}  {'-' * w_tasks}  {'-' * 7}"
    )
    print(header)
    print(rule)
    for r in rows:
        print(
            f"{r['frames']:>{w_frames}}  {r['ra']:<{w_ra}}  {r['dec']:<{w_dec}}  "
            f"{r['obj']:>{w_obj}}  {r['tasks']:>{w_tasks}}  {r['names']}"
        )


def histogram_figure_get(args):
    """
    Generates plotly figure with histogram data.
    """

    histo = histogram(args)

    y_labels = list(range(90, -90, -1))
    y_labels = list(map(lambda a: str(a), y_labels))

    x_labels = list(map(lambda a: deg2rah(a), range(0, 360, 1)))

    labels = dict(x="Right Ascension (h:m/deg)",
                  y="Declination (deg)", color="# of frames")

    pandas = pd.DataFrame(histo)
    fig = px.imshow(pandas, labels=labels, y=y_labels, x=x_labels)

    fig['layout']['yaxis']['autorange'] = "reversed"

    return fig


def histogram_show(args):
    """
    Shows a histogram of image density for the whole sky
    """

    fig = histogram_figure_get(args)

    fig.show()
