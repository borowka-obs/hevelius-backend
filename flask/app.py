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

from hevelius import cmd_stats, db

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
jwt_secret = config.get('JWT', {}).get('SECRET_KEY') or os.getenv('JWT_SECRET_KEY')

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


@app.route('/')
def root():
    """Just a stub API homepage."""
    return "Home🏠 EE"


@app.route('/histo')
def histogram():
    """Generates 2D diagram of observation density. Returns a HTML page with
    embedded plotly image."""

    fig = cmd_stats.histogram_figure_get({})

    graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    return render_template('histogram.html', graphJSON=graph_json)



@app.route('/api/tasks', methods=['POST', 'GET'])
def tasks():
    """
    Flask method used when a list of tasks is required.
    """

    user_id = get_param(request, 'user_id')
    limit = get_param(request, 'limit')

    query = "SELECT task_id, tasks.user_id, aavso_id, object, ra, decl, " \
        "exposure, descr, filter, binning, guiding, dither, " \
        "calibrate, solve, other_cmd, " \
        "min_alt, moon_distance, skip_before, skip_after, " \
        "min_interval, comment, state, imagename, " \
        "created, activated, performed, max_moon_phase, " \
        "max_sun_alt, auto_center, calibrated, solved, " \
        "sent FROM tasks, users WHERE tasks.user_id = users.user_id"
    params = []
    if user_id is not None:
        query = query + " AND tasks.user_id=%s"
        params.append(user_id)

    query = query + " ORDER by task_id DESC"

    if limit is not None:
        query = query + " LIMIT %s"
        params.append(limit)

    cnx = db.connect()
    tasks_list = db.run_query(cnx, query, params)
    cnx.close()

    return tasks_list


def sanitize(txt: str) -> str:
    """
    Sanitizes x input (removes backslashes)
    """
    txt = str(txt).replace('\'', '')  # apostrophes are bad
    txt = txt.replace(';', '')  # commas also
    txt = txt.replace('\\', '')  # and backslashes
    return txt


def get_param(req, field) -> str:
    """
    Attempts to retrieve parameter passed in JSON
    """
    json_html_request = req.get_json()
    param = json_html_request.get(field)
    if param:
        return sanitize(param)
    return param


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
        if task_data['user_id'] != current_user_id:
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

        # Create SQL query
        fields_str = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(values))  # Use SQL placeholders
        query = f"""INSERT INTO tasks ({fields_str}, state) VALUES ({placeholders}, 0) RETURNING task_id"""

        try:
            cnx = db.connect()
            result = db.run_query(cnx, query, values)
            print(f"#### Result: {result}")
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
            print(f"#### Exception: {e}")
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
        query = """SELECT task_id, tasks.user_id, aavso_id, object, ra, decl,
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
                'sent': bool(task[31])
            }
            formatted_tasks.append(task_dict)

        return formatted_tasks


# Register blueprint
api.register_blueprint(blp)
