"""
Flask application that provides a REST API to the Hevelius backend.
"""

import os
from flask import Flask, render_template, request
from flask_cors import CORS
from flask_smorest import Api, Blueprint
import yaml
import json
import plotly
from marshmallow import Schema, fields, ValidationError, validate
from flask.views import MethodView
from datetime import datetime, timedelta
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

from hevelius import cmd_stats, db, config as hevelius_config
from hevelius.version import VERSION

# By default, Flask searches for templates in the templates/ dir.
# Other params: debug=True, port=8080

# Initialize Flask app
app = Flask(__name__)
CORS(app, support_credentials=True)

# Load OpenAPI spec from YAML
dir_path = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(dir_path, 'openapi.yaml')) as f:
    spec = yaml.safe_load(f)

# Configure API documentation
app.config["API_TITLE"] = spec["info"]["title"]
app.config["API_VERSION"] = spec["info"]["version"]
app.config["OPENAPI_VERSION"] = spec["openapi"]
app.config["OPENAPI_URL_PREFIX"] = "/"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
app.config["API_SPEC_OPTIONS"] = {"spec": spec}

# Load JWT configuration from the config system
config = db.config  # Reuse the configuration from db.py

if config.get('jwt') and config.get('jwt').get('secret-key'):
    jwt_secret = config.get('jwt').get('secret-key')
else:
    jwt_secret = os.getenv('JWT_SECRET_KEY')

if not jwt_secret:
    print("JWT_SECRET_KEY not found in config or environment variables")
    exit(1)

app.config["JWT_SECRET_KEY"] = jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)  # Token expiration time
jwt = JWTManager(app)

# Initialize API
api = Api(app)

# Create blueprint
blp = Blueprint("api", __name__, url_prefix="/api")


# Define schemas for request/response validation
class LoginRequestSchema(Schema):
    username = fields.String(
        required=True,
        metadata={"description": "Username"}
    )
    password = fields.String(
        required=True,
        metadata={"description": "Password MD5 hash"}
    )


class LoginResponseSchema(Schema):
    status = fields.Boolean()
    token = fields.String()
    user_id = fields.Integer()
    firstname = fields.String()
    lastname = fields.String()
    share = fields.Float()
    phone = fields.String()
    email = fields.String()
    permissions = fields.Integer()
    aavso_id = fields.String()
    ftp_login = fields.String()
    ftp_pass = fields.String()
    msg = fields.String()


class TaskAddRequestSchema(Schema):
    user_id = fields.Integer(
        required=True,
        metadata={"description": "User ID"}
    )
    scope_id = fields.Integer(
        required=True,
        metadata={"description": "Scope ID"}
    )
    state = fields.Integer(
        validate=validate.OneOf([0, 1], error="State must be either 0 or 1"),
        load_default=1,  # Default to 1 if not specified
        metadata={"description": "Task state (0 - disabled, 1 - new)"}
    )
    object = fields.String(
        validate=validate.Length(min=1, max=64, error="Object name must be 64 characters or less"),
        metadata={"description": "Object name"}
    )
    ra = fields.Float(
        required=True,
        validate=validate.Range(min=0.0, max=24.0, error="RA must be between 0 and 24"),
        metadata={"description": "Right Ascension (0-24)"}
    )
    decl = fields.Float(
        required=True,
        validate=validate.Range(min=-90.0, max=90.0, error="Declination must be between -90 and 90"),
        metadata={"description": "Declination (-90 to 90)"}
    )
    exposure = fields.Float(
        metadata={"description": "Exposure time"}
    )
    descr = fields.String(
        validate=validate.Length(max=1024, error="Description must be 1024 characters or less"),
        metadata={"description": "Description"}
    )
    filter = fields.String(
        validate=validate.Length(max=16, error="Filter must be 16 characters or less"),
        metadata={"description": "Filter type"}
    )
    binning = fields.Integer(
        metadata={"description": "Binning value (1 - 1x1, 2 - 2x2, 3 - 3x3, 4 - 4x4)"}
    )
    guiding = fields.Boolean(
        load_default=True,
        metadata={"description": "Enable guiding"}
    )
    dither = fields.Boolean(
        load_default=False,
        metadata={"description": "Enable dithering"}
    )
    calibrate = fields.Boolean(
        metadata={"description": "Enable calibration"}
    )
    solve = fields.Boolean(
        metadata={"description": "Enable plate solving"}
    )
    other_cmd = fields.String(
        validate=lambda x: len(x) <= 512 or ValidationError("Additional commands must be 512 characters or less"),
        metadata={"description": "Additional commands"}
    )
    min_alt = fields.Float(
        metadata={"description": "Minimum altitude"}
    )
    moon_distance = fields.Float(
        metadata={"description": "Minimum moon distance"}
    )
    skip_before = fields.DateTime(
        load_default=datetime(2000, 1, 1),
        metadata={"description": "Skip before date"}
    )
    skip_after = fields.DateTime(
        load_default=datetime(3000, 1, 1),
        metadata={"description": "Skip after date"}
    )
    min_interval = fields.Integer(
        metadata={"description": "Minimum interval"}
    )
    comment = fields.String(
        metadata={"description": "Comment"}
    )
    max_moon_phase = fields.Integer(
        metadata={"description": "Maximum moon phase"}
    )
    max_sun_alt = fields.Integer(
        metadata={"description": "Maximum sun altitude"}
    )


class TaskAddResponseSchema(Schema):
    status = fields.Boolean(
        required=True,
        metadata={"description": "Operation status"}
    )
    task_id = fields.Integer(
        metadata={"description": "Created task ID"}
    )
    msg = fields.String(
        metadata={"description": "Status message"}
    )


class TasksRequestSchema(Schema):
    user_id = fields.Integer(
        required=False,
        metadata={"description": "Filter tasks by user ID"}
    )
    limit = fields.Integer(
        required=False,
        metadata={"description": "Maximum number of tasks to return"}
    )


class Task(Schema):
    task_id = fields.Integer(required=True, metadata={"description": "Task ID"})
    user_id = fields.Integer(required=True, metadata={"description": "User ID"})
    scope_id = fields.Integer(required=True, metadata={"description": "Telescope ID"})
    aavso_id = fields.String(metadata={"description": "AAVSO identifier"})
    object = fields.String(metadata={"description": "Object name"})
    ra = fields.Float(metadata={"description": "Right Ascension"})
    decl = fields.Float(metadata={"description": "Declination"})
    exposure = fields.Float(metadata={"description": "Exposure time"})
    descr = fields.String(metadata={"description": "Description"})
    filter = fields.String(metadata={"description": "Filter type"})
    binning = fields.Integer(metadata={"description": "Binning value"})
    guiding = fields.Boolean(metadata={"description": "Guiding enabled"})
    dither = fields.Boolean(metadata={"description": "Dithering enabled"})
    calibrate = fields.Boolean(metadata={"description": "Calibration enabled"})
    solve = fields.Boolean(metadata={"description": "Plate solving enabled"})
    other_cmd = fields.String(metadata={"description": "Additional commands"})
    min_alt = fields.Float(metadata={"description": "Minimum altitude"})
    moon_distance = fields.Float(metadata={"description": "Moon distance"})
    skip_before = fields.DateTime(metadata={"description": "Skip before date"})
    skip_after = fields.DateTime(metadata={"description": "Skip after date"})
    min_interval = fields.Integer(metadata={"description": "Minimum interval"})
    comment = fields.String(metadata={"description": "Comment"})
    state = fields.Integer(metadata={"description": "Task state"})
    imagename = fields.String(metadata={"description": "Image filename"})
    created = fields.DateTime(metadata={"description": "Creation timestamp"})
    activated = fields.DateTime(metadata={"description": "Activation timestamp"})
    performed = fields.DateTime(metadata={"description": "Execution timestamp"})
    max_moon_phase = fields.Integer(metadata={"description": "Maximum moon phase"})
    max_sun_alt = fields.Integer(metadata={"description": "Maximum sun altitude"})
    auto_center = fields.Boolean(metadata={"description": "Auto centering enabled"})
    calibrated = fields.Boolean(metadata={"description": "Calibration status"})
    solved = fields.Boolean(metadata={"description": "Plate solving status"})
    sent = fields.Boolean(metadata={"description": "Sent status"})


class TasksList(Schema):
    tasks = fields.List(fields.Nested(Task))


class VersionResponseSchema(Schema):
    version = fields.String(required=True, metadata={"description": "Hevelius version"})


class TaskGetResponseSchema(Schema):
    task = fields.Nested(Task)
    status = fields.Boolean(required=True)
    msg = fields.String()


class TaskUpdateRequestSchema(Schema):
    task_id = fields.Integer(required=True, metadata={"description": "Task ID to update"})
    # All other fields are optional
    user_id = fields.Integer(metadata={"description": "User ID"})
    scope_id = fields.Integer(metadata={"description": "Scope ID"})
    object = fields.String(
        validate=validate.Length(max=64, error="Object name must be 64 characters or less"),
        metadata={"description": "Object name"}
    )
    ra = fields.Float(
        validate=validate.Range(min=0.0, max=24.0, error="RA must be between 0 and 24"),
        metadata={"description": "Right Ascension (0-24)"}
    )
    decl = fields.Float(
        validate=validate.Range(min=-90.0, max=90.0, error="Declination must be between -90 and 90"),
        metadata={"description": "Declination (-90 to 90)"}
    )
    exposure = fields.Float(metadata={"description": "Exposure time"})
    descr = fields.String(
        validate=validate.Length(max=1024, error="Description must be 1024 characters or less"),
        metadata={"description": "Description"}
    )
    filter = fields.String(
        validate=validate.Length(max=16, error="Filter must be 16 characters or less"),
        metadata={"description": "Filter type"}
    )
    binning = fields.Integer(metadata={"description": "Binning value"})
    guiding = fields.Boolean(metadata={"description": "Enable guiding"})
    dither = fields.Boolean(metadata={"description": "Enable dithering"})
    calibrate = fields.Boolean(metadata={"description": "Enable calibration"})
    solve = fields.Boolean(metadata={"description": "Enable plate solving"})
    other_cmd = fields.String(
        validate=lambda x: len(x) <= 512 or ValidationError("Additional commands must be 512 characters or less"),
        metadata={"description": "Additional commands"}
    )
    min_alt = fields.Float(metadata={"description": "Minimum altitude"})
    moon_distance = fields.Float(metadata={"description": "Minimum moon distance"})
    skip_before = fields.DateTime(metadata={"description": "Skip before date"})
    skip_after = fields.DateTime(metadata={"description": "Skip after date"})
    min_interval = fields.Integer(metadata={"description": "Minimum interval"})
    comment = fields.String(metadata={"description": "Comment"})
    max_moon_phase = fields.Integer(metadata={"description": "Maximum moon phase"})
    max_sun_alt = fields.Integer(metadata={"description": "Maximum sun altitude"})


class TaskUpdateResponseSchema(Schema):
    status = fields.Boolean(required=True, metadata={"description": "Operation status"})
    msg = fields.String(metadata={"description": "Status message"})


# Add new schema for night plan request
class NightPlanRequestSchema(Schema):
    scope_id = fields.Integer(required=True, metadata={"description": "Telescope ID"})
    user_id = fields.Integer(metadata={"description": "Optional User ID filter"})


@app.route('/')
def root():
    """Just a stub API homepage."""
    return "Nothing to see here. Move along."


@app.route('/histo')
def histogram():
    """Generates 2D diagram of observation density. Returns a HTML page with
    embedded plotly image."""

    fig = cmd_stats.histogram_figure_get({})

    graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    return render_template('histogram.html', graphJSON=graph_json)


@blp.route("/login")
class LoginResource(MethodView):
    @blp.arguments(LoginRequestSchema)
    @blp.response(200, LoginResponseSchema)
    def post(self, login_data):
        """Login endpoint
        Returns user information and JWT token if credentials are valid
        """
        user = login_data.get('username')
        md5pass = login_data.get('password')

        if user is None:
            return {'status': False, 'msg': 'Username not provided'}
        if md5pass is None:
            return {'status': False, 'msg': 'Password not provided'}

        query = """SELECT user_id, pass_d, login, firstname, lastname, share, phone, email, permissions,
                aavso_id, ftp_login, ftp_pass FROM users WHERE login=%s"""

        cnx = db.connect()
        db_resp = db.run_query(cnx, query, (user,))
        cnx.close()

        if db_resp is None or not len(db_resp):
            print(f"Login: No such username ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        query = """SELECT user_id, pass_d, login, firstname, lastname, share, phone, email, permissions,
            aavso_id, ftp_login, ftp_pass FROM users WHERE login=%s"""
        params = [user]

        cnx = db.connect()
        db_resp = db.run_query(cnx, query, params)
        cnx.close()

        user_id, pass_db, _, firstname, lastname, share, phone, email, permissions, aavso_id, \
            ftp_login, ftp_pass = db_resp[0]

        if md5pass.lower() != pass_db.lower():
            print(f"Login: Invalid password for user ({user})")
            # Password's MD5 did not match
            return {'status': False, 'msg': 'Invalid credentials'}

        # Create JWT access token
        access_token = create_access_token(
            identity=user_id,
            additional_claims={
                'permissions': permissions,
                'username': user
            }
        )

        print(f"User {user} logged in successfully, generated JWT token.")
        return {
            'status': True,
            'token': access_token,  # Add JWT token to response
            'user_id': user_id,
            'firstname': firstname,
            'lastname': lastname,
            'share': share,
            'phone': phone,
            'email': email,
            'permissions': permissions,
            'aavso_id': aavso_id,
            'ftp_login': ftp_login,
            'ftp_pass': ftp_pass,
            'msg': 'Welcome'
        }


@blp.route("/task-add")
class TaskAddResource(MethodView):
    @jwt_required()  # Add this decorator to protect the endpoint
    @blp.arguments(TaskAddRequestSchema)
    @blp.response(200, TaskAddResponseSchema)
    def post(self, task_data):
        """Add new astronomical observation task"""
        # Get user ID from JWT token
        current_user_id = get_jwt_identity()

        # Optional: verify that the user_id in the request matches the token
        # Allow adding for other users in testing mode
        if (task_data['user_id'] != current_user_id) and (app.testing == False):
            return {
                'status': False,
                'msg': 'Unauthorized: token user_id does not match request user_id'
            }

        # Prepare fields for SQL query
        fields = []
        values = []
        for key, value in task_data.items():
            if value is not None:
                fields.append(key)
                values.append(value)
        if 'state' not in task_data.keys():
            fields.append('state')
            values.append(1)

        # Create SQL query
        fields_str = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(values))  # Use SQL placeholders
        # The default state is 1 (new)
        query = f"""INSERT INTO tasks ({fields_str}) VALUES ({placeholders}) RETURNING task_id"""

        try:
            cfg = hevelius_config.config_db_get()

            cnx = db.connect(cfg)
            result = db.run_query(cnx, query, values)
            cnx.close()

            if result and isinstance(result, int):
                return {
                    'status': True,
                    'task_id': result,
                    'msg': f'Task {result} created successfully'
                }

            return {
                'status': False,
                'msg': 'Failed to create task'
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
    @blp.arguments(TasksRequestSchema)
    @blp.response(200, TasksList)
    def get(self):
        """Get list of tasks
        Returns a list of astronomical observation tasks, optionally filtered by user_id
        """
        # Get parameters from query string for GET request
        user_id = request.args.get('user_id', type=int)
        limit = request.args.get('limit', type=int)

        tasks = self._get_tasks(user_id, limit)
        return {"tasks": tasks}

    @jwt_required()
    @blp.arguments(TasksRequestSchema)
    @blp.response(200, TasksList)
    def post(self, task_data):
        """Get list of tasks
        Returns a list of astronomical observation tasks, optionally filtered by user_id
        """
        # Get parameters from request body for POST request
        user_id = task_data.get('user_id')
        limit = task_data.get('limit')

        tasks = self._get_tasks(user_id, limit)

        return {"tasks": tasks}

    def _get_tasks(self, user_id=None, limit=None):
        """Helper method to get tasks based on filters"""
        query = """SELECT task_id, tasks.user_id, scope_id, aavso_id, object, ra, decl,
            exposure, descr, filter, binning, guiding, dither,
            calibrate, solve, other_cmd,
            min_alt, moon_distance, skip_before, skip_after,
            min_interval, comment, state, imagename,
            created, activated, performed, max_moon_phase,
            max_sun_alt, auto_center, calibrated, solved,
            sent FROM tasks, users WHERE tasks.user_id = users.user_id"""

        if user_id is not None:
            query = query + f" AND tasks.user_id={user_id}"

        query = query + " ORDER by task_id DESC"

        if limit is not None:
            query = query + f" LIMIT {limit}"

        cnx = db.connect()
        tasks_list = db.run_query(cnx, query)
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

        return formatted_tasks


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
    @blp.arguments(Schema.from_dict({"task_id": fields.Integer(required=True)}), location="query")
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
            sent, scope_id FROM tasks, users WHERE task_id = %s"""

        cnx = db.connect()
        task = db.run_query(cnx, query, (task_id,))
        cnx.close()

        if not task:
            return {
                'status': False,
                'msg': f'Task {task_id} not found',
                'task': None
            }

        task = task[0]  # Get first (and should be only) result

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
            'scope_id': task[32]
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
        current_user_id = get_jwt_identity()
        task_id = task_data.pop('task_id')  # Remove task_id from update fields

        # First check if the task exists and get its user_id
        query = "SELECT user_id FROM tasks WHERE task_id = %s"

        cnx = db.connect()
        result = db.run_query(cnx, query, (task_id,))
        cnx.close()

        if not result:
            return {
                'status': False,
                'msg': f'Task {task_id} not found'
            }

        task_user_id = result[0][0]

        # Check if the current user owns the task
        if task_user_id != current_user_id:
            return {
                'status': False,
                'msg': 'Unauthorized: you can only update your own tasks'
            }

        # Prepare fields for SQL query
        update_parts = []
        values = []
        for key, value in task_data.items():
            if value is not None:
                update_parts.append(f"{key} = %s")
                values.append(value)

        if not update_parts:
            return {
                'status': False,
                'msg': 'No fields to update'
            }

        # Add task_id as the last parameter
        values.append(task_id)

        # Create SQL query
        query = f"""UPDATE tasks SET {", ".join(update_parts)} WHERE task_id = %s"""

        try:
            cfg = hevelius_config.config_db_get()

            cnx = db.connect(cfg)
            result = db.run_query(cnx, query, values)
            cnx.close()

            if result:
                return {
                    'status': True,
                    'msg': f'Task {task_id} updated successfully'
                }
            return {
                'status': True,
                'msg': f'Task {task_id} updated successfully'
            }

        except Exception as e:
            print(f"ERROR: Exception while handling /task-update call: {e}")
            return {
                'status': False,
                'msg': f'Error updating task: {str(e)}'
            }


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
            AND state IN (1, 2, 3)
            AND (skip_before IS NULL OR skip_before < NOW())
            AND (skip_after IS NULL OR skip_after > NOW())"""

        values = [scope_id]

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


# Register blueprint
api.register_blueprint(blp)


if __name__ == '__main__':
    app.run()
