"""Task, night-plan, and version API routes."""

import logging

from flask import current_app
from flask.views import MethodView
from flask_jwt_extended import jwt_required


from hevelius import db, config as hevelius_config
from hevelius.version import VERSION
from hevelius.api.auth_utils import (
    _jwt_user_id_int,
)
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    NightPlanRequestSchema,
    TaskAddRequestSchema,
    TaskAddResponseSchema,
    TaskFindByFilenameQuerySchema,
    TaskFindByFilenameResponseSchema,
    TaskGetQuerySchema,
    TaskGetResponseSchema,
    TaskUpdateRequestSchema,
    TaskUpdateResponseSchema,
    TasksFilenameListQuerySchema,
    TasksFilenameListResponseSchema,
    TasksList,
    TasksRequestSchema,
    VersionResponseSchema,
)

logger = logging.getLogger(__name__)


def _escape_sql_like_suffix_pattern(filename: str) -> str:
    """Build LIKE pattern for paths ending with filename; escape %, _, \\ for ESCAPE E'\\\\'."""
    escaped = (
        filename.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return "%" + escaped


@blp.route("/task-add")
class TaskAddResource(MethodView):
    @jwt_required()  # Add this decorator to protect the endpoint
    @blp.arguments(TaskAddRequestSchema)
    @blp.response(200, TaskAddResponseSchema)
    def post(self, task_data):
        """Add new astronomical observation task"""
        # Get user ID from JWT token
        current_user_id = _jwt_user_id_int()

        # Optional: verify that the user_id in the request matches the token
        # Allow adding for other users in testing mode
        if (task_data['user_id'] != current_user_id) and not current_app.testing:
            return {
                'status': False,
                'msg': 'Unauthorized: token user_id does not match request user_id'
            }

        # Prepare fields for SQL query (project ids are handled via task_projects table)
        project_ids = task_data.pop('project_ids', None) or []
        project_id = task_data.pop('project_id', None)
        filter_id = task_data.pop('filter_id', None)
        if project_id is not None:
            project_ids.append(project_id)

        cnx = db.connect()
        if filter_id is not None:
            frow = db.run_query(cnx, "SELECT short_name FROM filters WHERE filter_id = %s", (filter_id,))
            if not frow:
                cnx.close()
                return {'status': False, 'msg': f'Filter {filter_id} not found'}
            task_data['filter'] = frow[0][0]

        if task_data.get('scope_id') is None and project_id is not None:
            prow = db.run_query(cnx, "SELECT scope_id FROM projects WHERE project_id = %s", (project_id,))
            if not prow:
                cnx.close()
                return {'status': False, 'msg': f'Project {project_id} not found'}
            task_data['scope_id'] = prow[0][0]

        if task_data.get('scope_id') is None:
            cnx.close()
            return {'status': False, 'msg': 'scope_id is required unless project_id is provided'}

        if task_data.get('state') == 6 and not task_data.get('imagename'):
            cnx.close()
            return {'status': False, 'msg': 'imagename is required when state is 6 (done)'}

        insert_fields = []
        values = []
        for key, value in task_data.items():
            if value is not None:
                insert_fields.append(key)
                values.append(value)
        if 'state' not in task_data.keys():
            insert_fields.append('state')
            values.append(1)

        # Create SQL query
        fields_str = ", ".join(insert_fields)
        placeholders = ", ".join(["%s"] * len(values))  # Use SQL placeholders
        # The default state is 1 (new)
        query = f"""INSERT INTO tasks ({fields_str}) VALUES ({placeholders}) RETURNING task_id"""

        try:
            cfg = hevelius_config.config_db_get()

            cnx.close()
            cnx = db.connect(cfg)
            result = db.run_query(cnx, query, values)
            if result is None:
                cnx.close()
                return {'status': False, 'msg': 'Failed to create task'}
            task_id = result if isinstance(result, int) else result[0] if result else None
            if not task_id:
                cnx.close()
                return {'status': False, 'msg': 'Failed to create task'}
            # Assign task to projects
            for pid in (project_ids or []):
                proj = db.run_query(cnx, "SELECT 1 FROM projects WHERE project_id = %s", (pid,))
                if proj:
                    db.run_query(cnx, "INSERT INTO task_projects (task_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (task_id, pid))
            cnx.close()

            return {
                'status': True,
                'task_id': task_id,
                'msg': f'Task {task_id} created successfully'
            }

        except Exception as e:
            print(f"ERROR: Exception while handling /task-add call: {e}")
            return {
                'status': False,
                'msg': f'Error creating task: {str(e)}'
            }


@blp.route("/tasks")
class TasksResource(MethodView):
    @jwt_required()
    @blp.arguments(TasksRequestSchema, location="query")
    @blp.response(200, TasksList)
    def get(self, args):
        """Get list of tasks with paging, sorting, and filtering"""
        return self._get_tasks(args)

    @jwt_required()
    @blp.arguments(TasksRequestSchema)
    @blp.response(200, TasksList)
    def post(self, args):
        """Get list of tasks with paging, sorting, and filtering"""
        return self._get_tasks(args)

    def _get_tasks(self, args):
        """Helper method to get tasks based on filters, sorting, and paging"""
        # Base query
        query = """SELECT tasks.task_id, tasks.user_id, users.login, tasks.scope_id, telescopes.name,
            users.aavso_id, tasks.object, tasks.ra, tasks.decl,
            tasks.exposure, tasks.descr, tasks.filter, tasks.binning, tasks.guiding, tasks.dither,
            tasks.calibrate, tasks.solve, tasks.other_cmd,
            tasks.min_alt, tasks.moon_distance, tasks.skip_before, tasks.skip_after,
            tasks.min_interval, tasks.comment, tasks.state, tasks.imagename,
            tasks.created, tasks.activated, tasks.performed, tasks.max_moon_phase,
            tasks.max_sun_alt, tasks.auto_center, tasks.calibrated, tasks.solved, tasks.sent
            FROM tasks
            JOIN users ON tasks.user_id = users.user_id
            LEFT JOIN telescopes ON tasks.scope_id = telescopes.scope_id
            WHERE 1=1"""

        count_query = """SELECT COUNT(*) FROM tasks
            JOIN users ON tasks.user_id = users.user_id
            WHERE 1=1"""

        # Build where clause and parameters
        where_clauses = []
        params = []

        # Apply filters
        if args.get('user_id'):
            where_clauses.append("tasks.user_id = %s")
            params.append(args['user_id'])

        if args.get('scope_id'):
            where_clauses.append("tasks.scope_id = %s")
            params.append(args['scope_id'])

        if args.get('object'):
            where_clauses.append("tasks.object ILIKE %s")
            params.append(f"%{args['object']}%")

        if args.get('ra_min') is not None:
            where_clauses.append("tasks.ra >= %s")
            params.append(args['ra_min'])

        if args.get('ra_max') is not None:
            where_clauses.append("tasks.ra <= %s")
            params.append(args['ra_max'])

        if args.get('decl_min') is not None:
            where_clauses.append("tasks.decl >= %s")
            params.append(args['decl_min'])

        if args.get('decl_max') is not None:
            where_clauses.append("tasks.decl <= %s")
            params.append(args['decl_max'])

        if args.get('exposure'):
            where_clauses.append("tasks.exposure = %s")
            params.append(args['exposure'])

        if args.get('descr'):
            where_clauses.append("tasks.descr ILIKE %s")
            params.append(f"%{args['descr']}%")

        if args.get('state') is not None:
            where_clauses.append("tasks.state = %s")
            params.append(args['state'])

        if args.get('project_id'):
            where_clauses.append("tasks.task_id IN (SELECT task_id FROM task_projects WHERE project_id = %s)")
            params.append(args['project_id'])

        if args.get('performed_after'):
            where_clauses.append("tasks.performed >= %s")
            params.append(args['performed_after'])

        if args.get('performed_before'):
            where_clauses.append("tasks.performed <= %s")
            params.append(args['performed_before'])

        # Add where clauses to queries
        if where_clauses:
            where_str = " AND " + " AND ".join(where_clauses)
            query += where_str
            count_query += where_str

        # Add sorting
        sort_field = args.get('sort_by', 'task_id')
        sort_field_map = {
            'task_id': 'tasks.task_id',
            'state': 'tasks.state',
            'object': 'tasks.object',
            'exposure': 'tasks.exposure',
            'skip_before': 'tasks.skip_before',
            'skip_after': 'tasks.skip_after',
            'ra': 'tasks.ra',
            'decl': 'tasks.decl',
            'created': 'tasks.created',
            'performed': 'tasks.performed',
            'user_id': 'tasks.user_id',
        }
        sort_field_sql = sort_field_map.get(sort_field, 'tasks.task_id')
        sort_order = args.get('sort_order', 'desc').upper()
        query += f" ORDER BY {sort_field_sql} {sort_order}"

        # Add pagination
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page
        query += f" LIMIT {per_page} OFFSET {offset}"

        # Execute queries
        cnx = db.connect()
        try:
            # Get total count
            total_count = db.run_query(cnx, count_query, params)[0][0]

            # Get paginated results
            tasks_list = db.run_query(cnx, query, params)
            task_ids = [t[0] for t in tasks_list]
            project_ids_by_task = {}
            if task_ids:
                placeholders = ",".join(["%s"] * len(task_ids))
                tp_rows = db.run_query(cnx, f"SELECT task_id, project_id FROM task_projects WHERE task_id IN ({placeholders})", task_ids)
                for tr in (tp_rows or []):
                    tid, pid = tr[0], tr[1]
                    if tid not in project_ids_by_task:
                        project_ids_by_task[tid] = []
                    project_ids_by_task[tid].append(pid)
        finally:
            cnx.close()

        # Format tasks
        formatted_tasks = []
        for task in tasks_list:
            task_dict = {
                'task_id': task[0],
                'user_id': task[1],
                'user_login': task[2],
                'scope_id': task[3],
                'scope_name': task[4],
                'aavso_id': task[5],
                'object': task[6],
                'ra': task[7],
                'decl': task[8],
                'exposure': task[9],
                'descr': task[10],
                'filter': task[11],
                'binning': task[12],
                'guiding': bool(task[13]),
                'dither': bool(task[14]),
                'calibrate': bool(task[15]),
                'solve': bool(task[16]),
                'other_cmd': task[17],
                'min_alt': task[18],
                'moon_distance': task[19],
                'skip_before': task[20],
                'skip_after': task[21],
                'min_interval': task[22],
                'comment': task[23],
                'state': task[24],
                'imagename': task[25],
                'created': task[26],
                'activated': task[27],
                'performed': task[28],
                'max_moon_phase': task[29],
                'max_sun_alt': task[30],
                'auto_center': bool(task[31]),
                'calibrated': bool(task[32]),
                'solved': bool(task[33]),
                'sent': bool(task[34]),
                'project_ids': sorted(project_ids_by_task.get(task[0], []))
            }
            formatted_tasks.append(task_dict)

        # Calculate total pages
        total_pages = (total_count + per_page - 1) // per_page

        return {
            "tasks": formatted_tasks,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages
        }


@blp.route("/task-find-by-filename")
class TaskFindByFilenameResource(MethodView):
    @jwt_required()
    @blp.arguments(TaskFindByFilenameQuerySchema, location="query")
    @blp.response(200, TaskFindByFilenameResponseSchema)
    def get(self, args):
        """Find tasks whose stored path (imagename) ends with the given filename string."""
        pattern = _escape_sql_like_suffix_pattern(args["filename"])
        query = (
            "SELECT task_id, imagename FROM tasks WHERE imagename IS NOT NULL "
            "AND imagename LIKE %s ESCAPE E'\\\\' ORDER BY task_id"
        )
        cnx = db.connect()
        rows = db.run_query(cnx, query, (pattern,))
        cnx.close()
        matches = [{"task_id": r[0], "filename": r[1]} for r in (rows or [])]
        return {"found": bool(matches), "matches": matches}


@blp.route("/tasks-filename-list")
class TasksFilenameListResource(MethodView):
    @jwt_required()
    @blp.arguments(TasksFilenameListQuerySchema, location="query")
    @blp.response(200, TasksFilenameListResponseSchema)
    def get(self, args):
        """Paginated compact [task_id, filename] list for all tasks (filename maps from imagename)."""
        page = args["page"]
        per_page = args["per_page"]
        offset = (page - 1) * per_page
        cnx = db.connect()
        total = db.run_query(cnx, "SELECT COUNT(*) FROM tasks")[0][0]
        data_rows = db.run_query(
            cnx,
            "SELECT task_id, imagename FROM tasks ORDER BY task_id LIMIT %s OFFSET %s",
            (per_page, offset),
        )
        cnx.close()
        rows = [[r[0], r[1]] for r in (data_rows or [])]
        total_pages = (total + per_page - 1) // per_page if per_page else 0
        return {
            "rows": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": total_pages,
        }


@blp.route("/version")
class VersionResource(MethodView):
    @blp.response(200, VersionResponseSchema)
    def get(self):
        """Version endpoint
        Returns the current version of Hevelius
        """
        return {"version": VERSION}


@blp.route("/task-get")
class TaskGetResource(MethodView):
    @jwt_required()
    @blp.arguments(TaskGetQuerySchema, location="query")
    @blp.response(200, TaskGetResponseSchema)
    def get(self, args):
        """Get single task details
        Returns details of a specific astronomical observation task
        """
        task_id = args['task_id']

        query = """SELECT task_id, tasks.user_id, aavso_id, object, ra, decl,
            exposure, descr, filter, binning, guiding, dither,
            calibrate, solve, other_cmd,
            min_alt, moon_distance, skip_before, skip_after,
            min_interval, comment, state, imagename,
            created, activated, performed, max_moon_phase,
            max_sun_alt, auto_center, calibrated, solved,
            sent, scope_id FROM tasks, users WHERE tasks.user_id = users.user_id AND task_id = %s"""

        cnx = db.connect()
        task = db.run_query(cnx, query, (task_id,))

        if not task:
            cnx.close()
            return {
                'status': False,
                'msg': f'Task {task_id} not found',
                'task': None
            }

        task = task[0]  # Get first (and should be only) result
        tp_rows = db.run_query(cnx, "SELECT project_id FROM task_projects WHERE task_id = %s", (task_id,))
        project_ids = sorted([r[0] for r in (tp_rows or [])])
        cnx.close()

        # Format the task data
        task_dict = {
            'task_id': task[0],
            'user_id': task[1],
            'aavso_id': task[2],
            'object': task[3],
            'ra': task[4],
            'decl': task[5],
            'exposure': task[6],
            'descr': task[7],
            'filter': task[8],
            'binning': task[9],
            'guiding': bool(task[10]),
            'dither': bool(task[11]),
            'calibrate': bool(task[12]),
            'solve': bool(task[13]),
            'other_cmd': task[14],
            'min_alt': task[15],
            'moon_distance': task[16],
            'skip_before': task[17],
            'skip_after': task[18],
            'min_interval': task[19],
            'comment': task[20],
            'state': task[21],
            'imagename': task[22],
            'created': task[23],
            'activated': task[24],
            'performed': task[25],
            'max_moon_phase': task[26],
            'max_sun_alt': task[27],
            'auto_center': bool(task[28]),
            'calibrated': bool(task[29]),
            'solved': bool(task[30]),
            'sent': bool(task[31]),
            'scope_id': task[32],
            'project_ids': project_ids
        }

        return {
            'status': True,
            'msg': 'Task found',
            'task': task_dict
        }


@blp.route("/task-update")
class TaskUpdateResource(MethodView):
    @jwt_required()
    @blp.arguments(TaskUpdateRequestSchema)
    @blp.response(200, TaskUpdateResponseSchema)
    def post(self, task_data):
        """Update existing astronomical observation task"""
        current_user_id = _jwt_user_id_int()
        task_id = task_data.pop('task_id')  # Remove task_id from update fields
        project_ids = task_data.pop('project_ids', None)  # Not a tasks column; handled below
        project_id = task_data.pop('project_id', None)
        filter_id = task_data.pop('filter_id', None)
        if project_id is not None:
            project_ids = [project_id]

        # First check if the task exists and get current values needed for validation
        query = "SELECT user_id, scope_id, state, imagename FROM tasks WHERE task_id = %s"

        cnx = db.connect()
        result = db.run_query(cnx, query, (task_id,))
        if not result:
            cnx.close()
            return {'status': False, 'msg': f'Task {task_id} not found'}

        task_user_id, _existing_scope_id, existing_state, existing_imagename = result[0]
        if task_user_id != current_user_id:
            cnx.close()
            return {'status': False, 'msg': 'Unauthorized: you can only update your own tasks'}

        if filter_id is not None:
            frow = db.run_query(cnx, "SELECT short_name FROM filters WHERE filter_id = %s", (filter_id,))
            if not frow:
                cnx.close()
                return {'status': False, 'msg': f'Filter {filter_id} not found'}
            task_data['filter'] = frow[0][0]

        if task_data.get('scope_id') is None and project_id is not None:
            prow = db.run_query(cnx, "SELECT scope_id FROM projects WHERE project_id = %s", (project_id,))
            if not prow:
                cnx.close()
                return {'status': False, 'msg': f'Project {project_id} not found'}
            task_data['scope_id'] = prow[0][0]

        resulting_state = task_data.get('state', existing_state)
        resulting_imagename = task_data.get('imagename', existing_imagename)
        if resulting_state == 6 and not resulting_imagename:
            cnx.close()
            return {'status': False, 'msg': 'imagename is required when state is 6 (done)'}

        # Prepare fields for SQL query (only tasks table columns)
        update_parts = []
        values = []
        for key, value in task_data.items():
            if value is not None:
                update_parts.append(f"{key} = %s")
                values.append(value)

        try:
            cfg = hevelius_config.config_db_get()
            cnx = db.connect(cfg)
            if update_parts:
                values.append(task_id)
                db.run_query(cnx, f"""UPDATE tasks SET {", ".join(update_parts)} WHERE task_id = %s""", values)
            # Update project assignments if project_ids was provided (replace entire list)
            if project_ids is not None:
                db.run_query(cnx, "DELETE FROM task_projects WHERE task_id = %s", (task_id,))
                for pid in project_ids:
                    proj = db.run_query(cnx, "SELECT 1 FROM projects WHERE project_id = %s", (pid,))
                    if proj:
                        db.run_query(cnx, "INSERT INTO task_projects (task_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (task_id, pid))
            cnx.close()
            return {'status': True, 'msg': f'Task {task_id} updated successfully'}
        except Exception as e:
            print(f"ERROR: Exception while handling /task-update call: {e}")
            return {'status': False, 'msg': f'Error updating task: {str(e)}'}


@blp.route("/night-plan")
class NightPlanResource(MethodView):
    @jwt_required()
    @blp.arguments(NightPlanRequestSchema, location="query")
    @blp.response(200, TasksList)
    def get(self, args):
        """Get list of tasks available for execution tonight
        Returns a list of astronomical observation tasks that can be executed during the current night
        """
        return self._get_night_plan(args)

    @jwt_required()
    @blp.arguments(NightPlanRequestSchema)
    @blp.response(200, TasksList)
    def post(self, args):
        """Get list of tasks available for execution tonight
        Returns a list of astronomical observation tasks that can be executed during the current night
        """
        return self._get_night_plan(args)

    def _get_night_plan(self, args):
        scope_id = args['scope_id']
        user_id = args.get('user_id')  # Optional parameter
        date = args.get('date')  # Optional parameter

        query = """SELECT task_id, tasks.user_id, scope_id, aavso_id, object, ra, decl,
            exposure, descr, filter, binning, guiding, dither,
            calibrate, solve, other_cmd,
            min_alt, moon_distance, skip_before, skip_after,
            min_interval, comment, state, imagename,
            created, activated, performed, max_moon_phase,
            max_sun_alt, auto_center, calibrated, solved,
            sent FROM tasks, users
            WHERE tasks.user_id = users.user_id
            AND scope_id = %s
            AND state IN (1, 2, 3)"""

        values = [scope_id]

        if date is not None:
            query += " AND (skip_before IS NULL OR skip_before < %s) AND (skip_after IS NULL OR skip_after > %s)"
            values.append(date)
            values.append(date)
        else:
            query += """
            AND (skip_before IS NULL OR skip_before < NOW())
            AND (skip_after IS NULL OR skip_after > NOW())"""

        if user_id is not None:
            query += " AND tasks.user_id = %s"
            values.append(user_id)

        query += " ORDER BY task_id DESC"

        cnx = db.connect()
        tasks_list = db.run_query(cnx, query, values)
        cnx.close()

        # Convert the raw database results to a list of task dictionaries
        formatted_tasks = []
        for task in tasks_list:
            task_dict = {
                'task_id': task[0],
                'user_id': task[1],
                'scope_id': task[2],
                'aavso_id': task[3],
                'object': task[4],
                'ra': task[5],
                'decl': task[6],
                'exposure': task[7],
                'descr': task[8],
                'filter': task[9],
                'binning': task[10],
                'guiding': bool(task[11]),
                'dither': bool(task[12]),
                'calibrate': bool(task[13]),
                'solve': bool(task[14]),
                'other_cmd': task[15],
                'min_alt': task[16],
                'moon_distance': task[17],
                'skip_before': task[18],
                'skip_after': task[19],
                'min_interval': task[20],
                'comment': task[21],
                'state': task[22],
                'imagename': task[23],
                'created': task[24],
                'activated': task[25],
                'performed': task[26],
                'max_moon_phase': task[27],
                'max_sun_alt': task[28],
                'auto_center': bool(task[29]),
                'calibrated': bool(task[30]),
                'solved': bool(task[31]),
                'sent': bool(task[32])
            }
            formatted_tasks.append(task_dict)

        return {"tasks": formatted_tasks}
