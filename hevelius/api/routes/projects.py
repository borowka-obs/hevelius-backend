import logging
from datetime import date, datetime

from flask import request
from flask.views import MethodView
from flask_jwt_extended import jwt_required
from flask_smorest import abort


from hevelius import db
from hevelius.api.auth_utils import (
    _jwt_user_id_int,
)
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    ProjectCreateSchema,
    ProjectDetailResponseSchema,
    ProjectSubframeCreateSchema,
    ProjectSubframeUpdateSchema,
    ProjectUpdateSchema,
    ProjectsListSchema,
)

logger = logging.getLogger(__name__)

_PROJECT_SELECT_COLS = (
    "project_id, name, description, regexps, scope_id, ra, decl, active, "
    "last_updated, total_integration_time, start_date, end_date, publications, rotation, "
    "focal, resx, resy, pixel_x, pixel_y"
)

_PROJECT_SELECT_COLS_P = (
    "p.project_id, p.name, p.description, p.regexps, p.scope_id, p.ra, p.decl, p.active, "
    "p.last_updated, p.total_integration_time, p.start_date, p.end_date, p.publications, p.rotation, "
    "p.focal, p.resx, p.resy, p.pixel_x, p.pixel_y"
)

_PROJECT_SORT_COLUMNS = {
    "project_id": "p.project_id",
    "name": "p.name",
    "last_updated": "p.last_updated",
    "total_integration_time": "p.total_integration_time",
    "start_date": "p.start_date",
    "end_date": "p.end_date",
}


def _projects_list_order_clause(sort_by: str, sort_order: str) -> str:
    if sort_by not in _PROJECT_SORT_COLUMNS:
        sort_by = "project_id"
    col = _PROJECT_SORT_COLUMNS[sort_by]
    if sort_order not in ("ASC", "DESC"):
        sort_order = "ASC"
    nulls = ""
    if sort_by == "last_updated":
        nulls = " NULLS LAST" if sort_order == "DESC" else " NULLS FIRST"
    elif sort_by in ("start_date", "end_date"):
        nulls = " NULLS LAST" if sort_order == "DESC" else " NULLS FIRST"
    return f"ORDER BY {col} {sort_order}{nulls}, p.project_id ASC"


def _sql_date_to_iso(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    s = str(val)
    return s[:10] if len(s) >= 10 else s


def _normalize_publications(val):
    if val is None:
        return None
    parts = [p.strip() for p in str(val).split() if p.strip()]
    return " ".join(parts) if parts else None


def _project_row_to_dict(r, subframes=None, user_ids=None):
    """Build project dict from a projects SELECT row (includes last_updated, total_integration_time, dates)."""
    return {
        "project_id": r[0], "name": r[1], "description": r[2], "regexps": r[3], "scope_id": r[4], "ra": r[5], "decl": r[6], "active": r[7],
        "last_updated": r[8], "total_integration_time": float(r[9]) if r[9] is not None else 0.0,
        "start_date": _sql_date_to_iso(r[10]),
        "end_date": _sql_date_to_iso(r[11]),
        "publications": _normalize_publications(r[12]),
        "rotation": r[13],
        "focal": r[14], "resx": r[15], "resy": r[16], "pixel_x": r[17], "pixel_y": r[18],
        "subframes": subframes or [], "user_ids": user_ids or []
    }


def _project_subframe_count(goal_count, count):
    """Prefer explicit count; otherwise keep backward-compatible goal_count value; default 0."""
    if count is not None:
        return int(count)
    if goal_count is not None:
        return int(goal_count)
    return 0


def _find_similar_project_names(cnx, name, exclude_id=None):
    """Return list of existing projects whose names are similar to name."""
    from hevelius.equipment import find_similar_project_names
    return find_similar_project_names(name, exclude_id=exclude_id, cnx=cnx)


@blp.route("/projects")
class ProjectsResource(MethodView):
    @jwt_required()
    @blp.response(200, ProjectsListSchema)
    def get(self):
        """Get list of projects with paging. Filter by user_id and/or scope_id (telescope)."""
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 100, type=int), 1000)
        user_id = request.args.get("user_id", type=int)
        scope_id = request.args.get("scope_id", type=int)
        sort_by = request.args.get("sort_by", "project_id")
        sort_order = (request.args.get("sort_order") or "asc").upper()
        order_sql = _projects_list_order_clause(sort_by, sort_order)
        offset = (page - 1) * per_page
        cnx = db.connect()
        if user_id is not None:
            count_q = "SELECT COUNT(*) FROM projects p JOIN project_users pu ON p.project_id = pu.project_id WHERE pu.user_id = %s"
            list_q = f"""SELECT {_PROJECT_SELECT_COLS_P}
                       FROM projects p JOIN project_users pu ON p.project_id = pu.project_id
                       WHERE pu.user_id = %s"""
            count_params, list_params = [user_id], [user_id]
            if scope_id is not None:
                count_q += " AND p.scope_id = %s"
                list_q += " AND p.scope_id = %s"
                count_params.append(scope_id)
                list_params.extend([scope_id, per_page, offset])
            else:
                list_params.extend([per_page, offset])
            list_q += f" {order_sql} LIMIT %s OFFSET %s"
            total = db.run_query(cnx, count_q, count_params)[0][0]
            rows = db.run_query(cnx, list_q, list_params)
        else:
            if scope_id is not None:
                count_q = "SELECT COUNT(*) FROM projects p WHERE p.scope_id = %s"
                list_q = f"""SELECT {_PROJECT_SELECT_COLS_P} FROM projects p
                            WHERE p.scope_id = %s {order_sql} LIMIT %s OFFSET %s"""
                total = db.run_query(cnx, count_q, (scope_id,))[0][0]
                rows = db.run_query(cnx, list_q, (scope_id, per_page, offset))
            else:
                count_q = "SELECT COUNT(*) FROM projects p"
                list_q = f"SELECT {_PROJECT_SELECT_COLS_P} FROM projects p {order_sql} LIMIT %s OFFSET %s"
                total = db.run_query(cnx, count_q)[0][0]
                rows = db.run_query(cnx, list_q, (per_page, offset))
        projects = []
        for r in (rows or []):
            pid = r[0]
            sub_q = """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                       ps.exposure_time, ps.goal_count, ps.count, ps.active, ps.last_updated
                       FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id
                       WHERE ps.project_id = %s"""
            sub_rows = db.run_query(cnx, sub_q, (pid,))
            user_q = "SELECT user_id FROM project_users WHERE project_id = %s"
            user_rows = db.run_query(cnx, user_q, (pid,))
            subframes = [
                {
                    "id": sr[0], "project_id": sr[1], "filter_id": sr[2],
                    "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
                    "exposure_time": sr[8], "goal_count": sr[9], "count": _project_subframe_count(sr[9], sr[10]), "active": sr[11],
                    "last_updated": sr[12],
                }
                for sr in (sub_rows or [])
            ]
            user_ids = [ur[0] for ur in (user_rows or [])]
            projects.append(_project_row_to_dict(r, subframes=subframes, user_ids=user_ids))
        cnx.close()
        pages = (total + per_page - 1) // per_page if total else 0
        return {"projects": projects, "total": total, "page": page, "per_page": per_page, "pages": pages}

    @jwt_required()
    @blp.arguments(ProjectCreateSchema, location="json")
    @blp.response(201)
    def post(self, body):
        """Create project. name and scope_id required. If ra/dec omitted, resolve from catalog by name.
        Optical params (focal, resx, resy, pixel_x, pixel_y) are auto-populated from the scope's sensor
        when not supplied; the caller may override any or all of them explicitly. rotation defaults to
        the telescope's default_rotation (if set) when not supplied."""
        name = body["name"]
        scope_id = body["scope_id"]
        description = body.get("description") or ""
        regexps = body.get("regexps")
        ra = body.get("ra")
        decl = body.get("decl")
        active = body.get("active", True)
        start_date = body.get("start_date")
        end_date = body.get("end_date")
        publications = _normalize_publications(body.get("publications"))
        rotation = body.get("rotation")
        focal = body.get("focal")
        resx = body.get("resx")
        resy = body.get("resy")
        pixel_x = body.get("pixel_x")
        pixel_y = body.get("pixel_y")
        cnx = db.connect()
        if ra is None or decl is None:
            cat = db.run_query(cnx, "SELECT object_id, name, ra, decl FROM objects WHERE lower(name)=%s", (name.strip().lower(),))
            if not cat:
                cnx.close()
                abort(400, message="Name not found in catalog; provide ra and dec to create project.")
            ra, decl = cat[0][2], cat[0][3]
        scope_row = db.run_query(
            cnx,
            "SELECT t.focal, s.resx, s.resy, s.pixel_x, s.pixel_y, t.default_rotation "
            "FROM telescopes t LEFT JOIN sensors s ON s.sensor_id = t.sensor_id "
            "WHERE t.scope_id = %s",
            (scope_id,)
        )
        if not scope_row:
            cnx.close()
            abort(400, message="Invalid scope_id: telescope not found.")
        sr = scope_row[0]
        if focal is None:
            focal = sr[0]
        if resx is None:
            resx = sr[1]
        if resy is None:
            resy = sr[2]
        if pixel_x is None:
            pixel_x = sr[3]
        if pixel_y is None:
            pixel_y = sr[4]
        if rotation is None:
            rotation = sr[5]
        similar = _find_similar_project_names(cnx, name)
        warnings = [
            f"Project with similar name '{p['name']}' already exists (id={p['project_id']})"
            for p in similar
        ]
        db.run_query(
            cnx,
            "INSERT INTO projects (name, description, regexps, scope_id, ra, decl, active, start_date, end_date, "
            "publications, rotation, focal, resx, resy, pixel_x, pixel_y) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (name, description, regexps, scope_id, ra, decl, active, start_date, end_date,
             publications, rotation, focal, resx, resy, pixel_x, pixel_y),
        )
        row = db.run_query(
            cnx,
            f"""SELECT {_PROJECT_SELECT_COLS}
                                   FROM projects
                                   WHERE name=%s AND scope_id=%s
                                   ORDER BY project_id DESC LIMIT 1""",
            (name, scope_id),
        )
        project_id = row[0][0]
        sub_rows = db.run_query(cnx, """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                   ps.exposure_time, ps.goal_count, ps.count, ps.active, ps.last_updated
                   FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id
                   WHERE ps.project_id = %s""", (project_id,))
        user_rows = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
        cnx.close()
        subframes = [
            {"id": sr[0], "project_id": sr[1], "filter_id": sr[2],
             "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
             "exposure_time": sr[8], "goal_count": sr[9], "count": _project_subframe_count(sr[9], sr[10]), "active": sr[11],
             "last_updated": sr[12]}
            for sr in (sub_rows or [])
        ]
        user_ids = [ur[0] for ur in (user_rows or [])]
        project = _project_row_to_dict(row[0], subframes=subframes, user_ids=user_ids)
        return {"status": True, "project_id": project_id, "project": project, "msg": "Created", "warnings": warnings}, 201


@blp.route("/projects/<int:project_id>")
class ProjectDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, ProjectDetailResponseSchema)
    def get(self, project_id):
        """Get single project with subframes and user IDs"""
        cnx = db.connect()
        row = db.run_query(
            cnx,
            f"SELECT {_PROJECT_SELECT_COLS} FROM projects WHERE project_id = %s",
            (project_id,),
        )
        if not row:
            cnx.close()
            return {"status": False, "project": None, "msg": f"Project {project_id} not found"}
        r = row[0]
        sub_q = """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                   ps.exposure_time, ps.goal_count, ps.count, ps.active, ps.last_updated FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id
                   WHERE ps.project_id = %s"""
        sub_rows = db.run_query(cnx, sub_q, (project_id,))
        user_rows = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
        cnx.close()
        subframes = [
            {
                "id": sr[0], "project_id": sr[1], "filter_id": sr[2],
                "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
                "exposure_time": sr[8], "goal_count": sr[9], "count": _project_subframe_count(sr[9], sr[10]), "active": sr[11],
                "last_updated": sr[12],
            }
            for sr in (sub_rows or [])
        ]
        user_ids = [ur[0] for ur in (user_rows or [])]
        project = _project_row_to_dict(r, subframes=subframes, user_ids=user_ids)
        return {"status": True, "project": project, "msg": "OK"}

    @jwt_required()
    @blp.arguments(ProjectUpdateSchema, location="json")
    @blp.response(200)
    def patch(self, body, project_id):
        """Update project fields."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
        if not row:
            cnx.close()
            abort(404, message=f"Project {project_id} not found")
        updates = []
        args = []
        for key in ("name", "description", "regexps", "scope_id", "ra", "decl", "active"):
            if key in body and body[key] is not None:
                updates.append(f"{key} = %s")
                args.append(body[key])
        for key in ("start_date", "end_date"):
            if key in body:
                updates.append(f"{key} = %s")
                args.append(body[key])
        if "publications" in body:
            updates.append("publications = %s")
            args.append(_normalize_publications(body["publications"]))
        if "rotation" in body:
            updates.append("rotation = %s")
            args.append(body["rotation"])   # None is valid — clears the value
        for key in ("focal", "resx", "resy", "pixel_x", "pixel_y"):
            if key in body:
                updates.append(f"{key} = %s")
                args.append(body[key])
        if updates:
            args.append(project_id)
            db.run_query(cnx, "UPDATE projects SET " + ", ".join(updates) + " WHERE project_id = %s", tuple(args))
        row = db.run_query(cnx, f"SELECT {_PROJECT_SELECT_COLS} FROM projects WHERE project_id = %s", (project_id,))
        sub_rows = db.run_query(cnx, """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                   ps.exposure_time, ps.goal_count, ps.count, ps.active, ps.last_updated
                   FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id WHERE ps.project_id = %s""", (project_id,))
        user_rows = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
        cnx.close()
        subframes = [
            {"id": sr[0], "project_id": sr[1], "filter_id": sr[2],
             "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
             "exposure_time": sr[8], "goal_count": sr[9], "count": _project_subframe_count(sr[9], sr[10]), "active": sr[11],
             "last_updated": sr[12]}
            for sr in (sub_rows or [])
        ]
        user_ids = [ur[0] for ur in (user_rows or [])]
        project = _project_row_to_dict(row[0], subframes=subframes, user_ids=user_ids)
        return {"status": True, "project": project, "msg": "Updated"}

    @jwt_required()
    @blp.response(200)
    def delete(self, project_id):
        """Delete project (subframes, user associations, and task links cascade automatically)."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
        if not row:
            cnx.close()
            abort(404, message=f"Project {project_id} not found")
        db.run_query(cnx, "DELETE FROM projects WHERE project_id = %s", (project_id,))
        cnx.close()
        return {"status": True, "msg": f"Project {project_id} deleted"}


def _resolve_filter_id(cnx, body, require_one=True):
    """Resolve filter_id from body: either filter (short name) or filter_id. Forbid both. Return (filter_id, error_msg)."""
    has_filter = body.get("filter") is not None and str(body.get("filter", "")).strip()
    has_filter_id = body.get("filter_id") is not None
    if has_filter and has_filter_id:
        return None, "Specify only one of filter (short name) or filter_id."
    if require_one and not has_filter and not has_filter_id:
        return None, "Specify either filter (short name) or filter_id."
    if has_filter_id:
        return body["filter_id"], None
    short_name = str(body["filter"]).strip()
    row = db.run_query(cnx, "SELECT filter_id FROM filters WHERE short_name = %s", (short_name,))
    if not row:
        return None, f"Filter short name '{short_name}' not found."
    return row[0][0], None


@blp.route("/projects/<int:project_id>/subframes")
class ProjectSubframesResource(MethodView):
    @jwt_required()
    @blp.arguments(ProjectSubframeCreateSchema, location="json")
    @blp.response(201)
    def post(self, body, project_id):
        """Add a subframe to a project."""
        cnx = db.connect()
        proj = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
        if not proj:
            cnx.close()
            abort(404, message=f"Project {project_id} not found")
        filter_id, err = _resolve_filter_id(cnx, body, require_one=True)
        if err:
            cnx.close()
            abort(400, message=err)
        exposure_time = body["exposure_time"]
        count = body.get("count")
        goal_count = body.get("goal_count")
        if count is None and goal_count is None:
            count = 0
            goal_count = 0
        elif count is None:
            count = goal_count
        elif goal_count is None:
            goal_count = count
        active = body.get("active", True)
        db.run_query(cnx, "INSERT INTO project_subframes (project_id, filter_id, exposure_time, goal_count, count, active) VALUES (%s, %s, %s, %s, %s, %s)",
                     (project_id, filter_id, exposure_time, goal_count, count, active))
        row = db.run_query(cnx, "SELECT id FROM project_subframes WHERE project_id = %s ORDER BY id DESC LIMIT 1", (project_id,))
        subframe_id = row[0][0]
        cnx.close()
        return {"status": True, "subframe_id": subframe_id, "msg": "Created"}, 201


@blp.route("/projects/<int:project_id>/subframes/<int:subframe_id>")
class ProjectSubframeDetailResource(MethodView):
    @jwt_required()
    @blp.arguments(ProjectSubframeUpdateSchema, location="json")
    @blp.response(200)
    def patch(self, body, project_id, subframe_id):
        """Update a subframe."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT id FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
        if not row:
            cnx.close()
            abort(404, message="Project or subframe not found")
        if body.get("filter") is not None and body.get("filter_id") is not None:
            cnx.close()
            abort(400, message="Specify only one of filter (short name) or filter_id.")
        filter_id = None
        if "filter" in body and body["filter"] is not None and str(body["filter"]).strip():
            filter_id, err = _resolve_filter_id(cnx, body, require_one=False)
            if err:
                cnx.close()
                abort(400, message=err)
        elif body.get("filter_id") is not None:
            filter_id = body["filter_id"]
        updates = []
        args = []
        # Each field is updated independently; count and goal_count are no longer
        # mirrored. This lets clients (e.g. the runner reporting captured frames)
        # bump count without disturbing the user-defined goal_count or active flag.
        for key, val in [("filter_id", filter_id), ("exposure_time", body.get("exposure_time")),
                         ("goal_count", body.get("goal_count")), ("count", body.get("count")),
                         ("active", body.get("active"))]:
            if val is not None:
                updates.append(f"{key} = %s")
                args.append(val)
        if updates:
            updates.append("last_updated = now()")
            args.extend([project_id, subframe_id])
            db.run_query(cnx, "UPDATE project_subframes SET " + ", ".join(updates) + " WHERE project_id = %s AND id = %s", tuple(args))
        cnx.close()
        return {"status": True, "msg": "Updated"}

    @jwt_required()
    @blp.response(200)
    def delete(self, project_id, subframe_id):
        """Remove a subframe from a project."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT id FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
        if not row:
            cnx.close()
            abort(404, message="Project or subframe not found")
        db.run_query(cnx, "DELETE FROM project_subframes WHERE project_id = %s AND id = %s", (project_id, subframe_id))
        cnx.close()
        return {"status": True, "msg": "Deleted"}


# Task state 6 = DONE (complete) per task_states
TASK_STATE_DONE = 6


@blp.route("/projects/<int:project_id>/stats")
class ProjectStatsResource(MethodView):
    @jwt_required()
    def get(self, project_id):
        """Get project statistics: total tasks, incomplete (state != 6), done (state = 6)."""
        cnx = db.connect()
        proj = db.run_query(cnx, "SELECT project_id FROM projects WHERE project_id = %s", (project_id,))
        if not proj:
            cnx.close()
            return {"status": False, "msg": f"Project {project_id} not found", "total_tasks": 0, "tasks_incomplete": 0, "tasks_done": 0}
        total = db.run_query(cnx, "SELECT COUNT(*) FROM task_projects WHERE project_id = %s", (project_id,))[0][0]
        incomplete = db.run_query(cnx, """SELECT COUNT(*) FROM task_projects tp JOIN tasks t ON tp.task_id = t.task_id
            WHERE tp.project_id = %s AND t.state != %s""", (project_id, TASK_STATE_DONE))[0][0]
        done = db.run_query(cnx, """SELECT COUNT(*) FROM task_projects tp JOIN tasks t ON tp.task_id = t.task_id
            WHERE tp.project_id = %s AND t.state = %s""", (project_id, TASK_STATE_DONE))[0][0]
        cnx.close()
        return {
            "status": True,
            "project_id": project_id,
            "total_tasks": total,
            "tasks_incomplete": incomplete,
            "tasks_done": done,
            "msg": "OK"
        }


@blp.route("/projects/<int:project_id>/tasks/<int:task_id>")
class ProjectTaskResource(MethodView):
    @jwt_required()
    def post(self, project_id, task_id):
        """Add a task to a project. Task must exist and be owned by the current user."""
        current_user_id = _jwt_user_id_int()
        cnx = db.connect()
        task_row = db.run_query(cnx, "SELECT user_id FROM tasks WHERE task_id = %s", (task_id,))
        if not task_row:
            cnx.close()
            return {"status": False, "msg": f"Task {task_id} not found"}
        if task_row[0][0] != current_user_id:
            cnx.close()
            return {"status": False, "msg": "Unauthorized: you can only add your own tasks to a project"}
        proj = db.run_query(cnx, "SELECT 1 FROM projects WHERE project_id = %s", (project_id,))
        if not proj:
            cnx.close()
            return {"status": False, "msg": f"Project {project_id} not found"}
        db.run_query(cnx, "INSERT INTO task_projects (task_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (task_id, project_id))
        cnx.close()
        return {"status": True, "msg": f"Task {task_id} added to project {project_id}"}

    @jwt_required()
    def delete(self, project_id, task_id):
        """Remove a task from a project. Task must exist and be owned by the current user."""
        current_user_id = _jwt_user_id_int()
        cnx = db.connect()
        task_row = db.run_query(cnx, "SELECT user_id FROM tasks WHERE task_id = %s", (task_id,))
        if not task_row:
            cnx.close()
            return {"status": False, "msg": f"Task {task_id} not found"}
        if task_row[0][0] != current_user_id:
            cnx.close()
            return {"status": False, "msg": "Unauthorized: you can only remove your own tasks from a project"}
        db.run_query(cnx, "DELETE FROM task_projects WHERE task_id = %s AND project_id = %s", (task_id, project_id))
        cnx.close()
        return {"status": True, "msg": f"Task {task_id} removed from project {project_id}"}
