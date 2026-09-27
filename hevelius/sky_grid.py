"""Generic SQL-side sky density grid aggregation.

Bins RA/Dec coordinates into a whole-sky grid of resolution_deg x
resolution_deg cells and counts rows per cell, entirely in a single SQL
GROUP BY query — this is what keeps the feature cheap regardless of table
size (80k rows today, up to ~1M+ later): the aggregation happens in
Postgres, and the number of returned (non-empty) cells is bounded by the
grid resolution (at most 360/resolution_deg * 180/resolution_deg cells),
not by the row count.

Bucketing rule for tasks: a task's cell is derived from
COALESCE(he_solved_ra, ra * 15), COALESCE(he_solved_dec, decl) — the actual
plate-solved frame center when one exists (most accurate — it's where the
frame actually landed), falling back to the nominal target position (RA
converted hours -> degrees) when it doesn't (task never got that far). This
is a single rule shared by both "all" and "completed" modes, so a task's
cell never moves depending on which mode is being viewed.

Only tasks in a "real" state (state >= 1, i.e. not a template or a deleted
row) are considered at all. "mode" then just picks which precomputed
per-cell metric (total vs. completed-only) is exposed as `count`/
`project_count` — both are computed in the same query pass via FILTER
clauses, so switching modes never needs a second round-trip.
"""

from hevelius import db

RESOLUTIONS_DEG = (1, 2, 5, 10)

_RA_EXPR = "COALESCE(t.he_solved_ra, t.ra * 15)"
_DECL_EXPR = "COALESCE(t.he_solved_dec, t.decl)"
# Wrap RA into [0, 360) so a value of exactly 360 (e.g. ra=24h) or any
# floating point overshoot doesn't fall outside the grid's bins.
_RA_WRAPPED_EXPR = f"(({_RA_EXPR}) - 360.0 * floor(({_RA_EXPR}) / 360.0))"


def sky_grid_payload(conn, resolution_deg=1, mode="completed", scope_id=None, include_projects=False):
    """
    Build a sparse sky density grid for tasks.

    :param conn: DB connection
    :param resolution_deg: grid bin size in degrees, one of RESOLUTIONS_DEG
    :param mode: "all" (every non-template, non-deleted task) or
        "completed" (state=6 only)
    :param scope_id: optional telescope/scope filter
    :param include_projects: when True, also compute the distinct
        project_count per bucket (projects with >=1 task in that bucket,
        under the active mode)
    :return: JSON-serialisable dict, see api/openapi.yaml for the full shape
    """
    if resolution_deg not in RESOLUTIONS_DEG:
        raise ValueError(f"resolution_deg must be one of {RESOLUTIONS_DEG}, got {resolution_deg!r}")
    if mode not in ("all", "completed"):
        raise ValueError(f"mode must be 'all' or 'completed', got {mode!r}")

    scope_filter_sql = ""
    if scope_id is not None:
        scope_filter_sql = "AND t.scope_id = %s"

    project_select = ""
    project_join = ""
    if include_projects:
        project_select = """,
        COUNT(DISTINCT tp.project_id) AS total_project_count,
        COUNT(DISTINCT tp.project_id) FILTER (WHERE tc.state = 6) AS completed_project_count"""
        project_join = "LEFT JOIN task_projects tp ON tp.task_id = tc.task_id"

    # NOTE: this must stay a plain "SELECT ... FROM (SELECT ...) AS tc ..."
    # (a derived table), not a "WITH ... AS (...) SELECT ..." CTE — the
    # low-level db_pgsql.run_query() only calls cursor.fetchall() when the
    # query text starts with "select" (see hevelius/db_pgsql.py), so a
    # leading "WITH" would silently return None instead of rows.
    # COUNT(DISTINCT tc.task_id) rather than COUNT(*): when include_projects
    # is set, the LEFT JOIN to task_projects produces one row per
    # (task, project) pair, so a plain COUNT(*) would over-count any task
    # assigned to more than one project. Counting distinct task_id is
    # correct whether or not that join is present.
    query = f"""
        SELECT
            floor(tc.ra_deg / %s) * %s AS ra_bin,
            floor(tc.decl_deg / %s) * %s AS decl_bin,
            COUNT(DISTINCT tc.task_id) AS total_count,
            COUNT(DISTINCT tc.task_id) FILTER (WHERE tc.state = 6) AS completed_count
            {project_select}
        FROM (
            SELECT t.task_id, t.state,
                   ({_RA_WRAPPED_EXPR}) AS ra_deg,
                   ({_DECL_EXPR}) AS decl_deg
            FROM tasks t
            WHERE ({_RA_EXPR}) IS NOT NULL
              AND ({_DECL_EXPR}) IS NOT NULL
              AND t.state >= 1
              {scope_filter_sql}
        ) AS tc
        {project_join}
        GROUP BY ra_bin, decl_bin
        ORDER BY ra_bin, decl_bin
    """
    # Param order must match the %s placeholders' left-to-right order in
    # the query text above: the 4 resolution_deg substitutions in the outer
    # SELECT come first, then the scope_id filter inside the subquery.
    params = [resolution_deg, resolution_deg, resolution_deg, resolution_deg]
    if scope_id is not None:
        params.append(scope_id)

    rows = db.run_query(conn, query, params)

    cells = []
    total_frames = 0
    for row in rows or []:
        ra_bin, decl_bin, total_count, completed_count = row[0], row[1], row[2], row[3]
        count = completed_count if mode == "completed" else total_count
        if not count:
            continue
        cell = {
            "ra_deg": int(ra_bin),
            "decl_deg": int(decl_bin),
            "count": int(count),
            "completed_count": int(completed_count),
        }
        if include_projects:
            total_project_count, completed_project_count = row[4], row[5]
            cell["project_count"] = int(completed_project_count if mode == "completed" else total_project_count)
        else:
            cell["project_count"] = None
        cells.append(cell)
        total_frames += count

    return {
        "resolution_deg": resolution_deg,
        "mode": mode,
        "scope_id": scope_id,
        "ra_bins": 360 // resolution_deg,
        "decl_bins": 180 // resolution_deg,
        "ra_unit": "deg",
        "total_frames": total_frames,
        "nonempty_cells": len(cells),
        "cells": cells,
    }
