"""
Flask application that provides a REST API to the Hevelius backend.
"""

import logging
import os
from flask import Flask, render_template

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


logger = logging.getLogger(__name__)

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


# Add new schema for sorting and filtering parameters
class TaskSortField(fields.String):
    def _validate(self, value):
        allowed_fields = [
            'task_id', 'state', 'object', 'exposure',
            'skip_before', 'skip_after', 'ra', 'decl',
            'created', 'performed', 'user_id'
        ]
        if value not in allowed_fields:
            raise ValidationError(f"Invalid sort field. Must be one of: {', '.join(allowed_fields)}")


class TasksRequestSchema(Schema):
    # Paging parameters
    page = fields.Integer(missing=1, validate=validate.Range(min=1),
                          metadata={"description": "Page number (starting from 1)"})
    per_page = fields.Integer(missing=100, validate=validate.Range(min=1, max=1000),
                              metadata={"description": "Number of items per page"})

    # Sorting parameters
    sort_by = TaskSortField(missing='task_id',
                            metadata={"description": "Field to sort by"})
    sort_order = fields.String(missing='desc', validate=validate.OneOf(['asc', 'desc']),
                               metadata={"description": "Sort order (asc or desc)"})

    # Filtering parameters
    user_id = fields.Integer(metadata={"description": "Filter by user ID"})
    scope_id = fields.Integer(metadata={"description": "Filter by scope ID"})
    object = fields.String(metadata={"description": "Filter by object name"})
    ra_min = fields.Float(metadata={"description": "Minimum RA value"})
    ra_max = fields.Float(metadata={"description": "Maximum RA value"})
    decl_min = fields.Float(metadata={"description": "Minimum declination value"})
    decl_max = fields.Float(metadata={"description": "Maximum declination value"})
    exposure = fields.Float(metadata={"description": "Filter by exposure time"})
    descr = fields.String(metadata={"description": "Filter by description"})
    state = fields.Integer(metadata={"description": "Filter by state"})
    performed_after = fields.DateTime(metadata={"description": "Filter tasks performed after this time"})
    performed_before = fields.DateTime(metadata={"description": "Filter tasks performed before this time"})


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
    total = fields.Integer(required=True, metadata={"description": "Total number of tasks"})
    page = fields.Integer(required=True, metadata={"description": "Current page number"})
    per_page = fields.Integer(required=True, metadata={"description": "Items per page"})
    pages = fields.Integer(required=True, metadata={"description": "Total number of pages"})


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
    date = fields.Date(required=False, metadata={"description": "Date in YYYY-MM-DD format"})


class SensorSchema(Schema):
    sensor_id = fields.Integer(required=True, metadata={"description": "Sensor ID"})
    name = fields.String(metadata={"description": "Sensor name"})
    resx = fields.Integer(metadata={"description": "Resolution in X axis (pixels)"})
    resy = fields.Integer(metadata={"description": "Resolution in Y axis (pixels)"})
    pixel_x = fields.Float(metadata={"description": "Pixel size in X axis (microns)"})
    pixel_y = fields.Float(metadata={"description": "Pixel size in Y axis (microns)"})
    bits = fields.Integer(metadata={"description": "Bit depth"})
    width = fields.Float(metadata={"description": "Sensor width (mm)"})
    height = fields.Float(metadata={"description": "Sensor height (mm)"})


class TelescopeSchema(Schema):
    scope_id = fields.Integer(required=True, metadata={"description": "Telescope ID"})
    name = fields.String(metadata={"description": "Telescope name"})
    descr = fields.String(metadata={"description": "Telescope description"})
    min_dec = fields.Float(metadata={"description": "Minimum declination"})
    max_dec = fields.Float(metadata={"description": "Maximum declination"})
    focal = fields.Float(metadata={"description": "Focal length (mm)"})
    aperture = fields.Float(metadata={"description": "Aperture (mm)"})
    lon = fields.Float(metadata={"description": "Longitude"})
    lat = fields.Float(metadata={"description": "Latitude"})
    alt = fields.Float(metadata={"description": "Altitude"})
    sensor = fields.Nested(SensorSchema, allow_none=True, metadata={"description": "Associated sensor"})
    active = fields.Boolean(metadata={"description": "Whether the telescope is active"})


class TelescopesListSchema(Schema):
    telescopes = fields.List(fields.Nested(TelescopeSchema))


class CatalogSchema(Schema):
    name = fields.String(required=True, metadata={"description": "Catalog name"})
    shortname = fields.String(required=True, metadata={"description": "Catalog short name"})
    filename = fields.String(metadata={"description": "Catalog filename"})
    descr = fields.String(metadata={"description": "Catalog description"})
    url = fields.String(metadata={"description": "Catalog URL"})
    version = fields.String(metadata={"description": "Catalog version"})


class ObjectSchema(Schema):
    object_id = fields.Integer(metadata={"description": "Object ID"})
    name = fields.String(required=True, metadata={"description": "Object name"})
    ra = fields.Float(metadata={"description": "Right Ascension"})
    decl = fields.Float(metadata={"description": "Declination"})
    descr = fields.String(metadata={"description": "Object description"})
    comment = fields.String(metadata={"description": "Object comment"})
    type = fields.String(metadata={"description": "Object type"})
    epoch = fields.String(metadata={"description": "Epoch"})
    const = fields.String(metadata={"description": "Constellation"})
    magn = fields.Float(metadata={"description": "Magnitude"})
    x = fields.Float(metadata={"description": "X coordinate"})
    y = fields.Float(metadata={"description": "Y coordinate"})
    altname = fields.String(metadata={"description": "Alternative name"})
    distance = fields.Float(metadata={"description": "Distance"})
    catalog = fields.String(required=True, metadata={"description": "Catalog short name"})


class ObjectSearchRequestSchema(Schema):
    query = fields.String(required=True, metadata={"description": "Search query"})
    limit = fields.Integer(missing=10, validate=validate.Range(min=1, max=100),
                           metadata={"description": "Maximum number of results"})


class ObjectsListRequestSchema(Schema):
    # Paging parameters
    page = fields.Integer(missing=1, validate=validate.Range(min=1),
                          metadata={"description": "Page number (starting from 1)"})
    per_page = fields.Integer(missing=100, validate=validate.Range(min=1, max=1000),
                              metadata={"description": "Number of items per page"})

    # Sorting parameters
    sort_by = fields.String(missing='name', validate=validate.OneOf(
        ['catalog', 'name', 'ra', 'decl', 'const', 'type', 'magn'],
        error="Invalid sort field. Must be one of: catalog, name, ra, decl, const, type, magn"
    ))
    sort_order = fields.String(missing='asc', validate=validate.OneOf(['asc', 'desc']),
                               metadata={"description": "Sort order (asc or desc)"})

    # Filtering parameters
    catalog = fields.String(metadata={"description": "Filter by catalog short name"})
    constellation = fields.String(metadata={"description": "Filter by constellation code (e.g. Sgr)"})
    name = fields.String(metadata={"description": "Filter by object name"})


class ObjectsListResponseSchema(Schema):
    objects = fields.List(fields.Nested(ObjectSchema))
    total = fields.Integer(required=True, metadata={"description": "Total number of objects"})
    page = fields.Integer(required=True, metadata={"description": "Current page number"})
    per_page = fields.Integer(required=True, metadata={"description": "Items per page"})
    pages = fields.Integer(required=True, metadata={"description": "Total number of pages"})


class ObjectSearchResponseSchema(Schema):
    objects = fields.List(fields.Nested(ObjectSchema))


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
        if (task_data['user_id'] != current_user_id) and not app.testing:
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
        query = """SELECT task_id, tasks.user_id, scope_id, aavso_id, object, ra, decl,
            exposure, descr, filter, binning, guiding, dither,
            calibrate, solve, other_cmd,
            min_alt, moon_distance, skip_before, skip_after,
            min_interval, comment, state, imagename,
            created, activated, performed, max_moon_phase,
            max_sun_alt, auto_center, calibrated, solved,
            sent FROM tasks, users WHERE tasks.user_id = users.user_id"""

        count_query = """SELECT COUNT(*) FROM tasks, users
            WHERE tasks.user_id = users.user_id"""

        # Build where clause and parameters
        where_clauses = []
        params = []

        # Apply filters
        if args.get('user_id'):
            where_clauses.append("tasks.user_id = %s")
            params.append(args['user_id'])

        if args.get('scope_id'):
            where_clauses.append("scope_id = %s")
            params.append(args['scope_id'])

        if args.get('object'):
            where_clauses.append("object ILIKE %s")
            params.append(f"%{args['object']}%")

        if args.get('ra_min') is not None:
            where_clauses.append("ra >= %s")
            params.append(args['ra_min'])

        if args.get('ra_max') is not None:
            where_clauses.append("ra <= %s")
            params.append(args['ra_max'])

        if args.get('decl_min') is not None:
            where_clauses.append("decl >= %s")
            params.append(args['decl_min'])

        if args.get('decl_max') is not None:
            where_clauses.append("decl <= %s")
            params.append(args['decl_max'])

        if args.get('exposure'):
            where_clauses.append("exposure = %s")
            params.append(args['exposure'])

        if args.get('descr'):
            where_clauses.append("descr ILIKE %s")
            params.append(f"%{args['descr']}%")

        if args.get('state') is not None:
            where_clauses.append("state = %s")
            params.append(args['state'])

        if args.get('performed_after'):
            where_clauses.append("performed >= %s")
            params.append(args['performed_after'])

        if args.get('performed_before'):
            where_clauses.append("performed <= %s")
            params.append(args['performed_before'])

        # Add where clauses to queries
        if where_clauses:
            where_str = " AND " + " AND ".join(where_clauses)
            query += where_str
            count_query += where_str

        # Add sorting
        sort_field = args.get('sort_by', 'task_id')
        sort_order = args.get('sort_order', 'desc').upper()
        query += f" ORDER BY {sort_field} {sort_order}"

        # Add pagination
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page
        query += f" LIMIT {per_page} OFFSET {offset}"

        # Execute queries
        cnx = db.connect()

        # Get total count
        total_count = db.run_query(cnx, count_query, params)[0][0]

        # Get paginated results
        tasks_list = db.run_query(cnx, query, params)
        cnx.close()

        # Format tasks
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

        # Calculate total pages
        total_pages = (total_count + per_page - 1) // per_page

        return {
            "tasks": formatted_tasks,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages
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


@blp.route("/scopes")
class ScopesResource(MethodView):
    @jwt_required()
    @blp.response(200, TelescopesListSchema)
    def get(self):
        """Get list of telescopes with their associated sensors"""
        # Query to get telescopes with their sensors
        query = """
            SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
                   t.lon, t.lat, t.alt, t.sensor_id, t.active,
                   s.sensor_id, s.name, s.resx, s.resy, s.pixel_x, s.pixel_y,
                   s.bits, s.width, s.height
            FROM telescopes t
            LEFT JOIN sensors s ON t.sensor_id = s.sensor_id
            ORDER BY t.scope_id
        """

        cnx = db.connect()
        results = db.run_query(cnx, query)
        cnx.close()

        telescopes = []
        for row in results:
            telescope = {
                'scope_id': row[0],
                'name': row[1],
                'descr': row[2],
                'min_dec': row[3],
                'max_dec': row[4],
                'focal': row[5],
                'aperture': row[6],
                'lon': row[7],
                'lat': row[8],
                'alt': row[9],
                'active': row[11]
            }

            # Add sensor data if available
            if row[10] is not None:  # if sensor_id is not null
                telescope['sensor'] = {
                    'sensor_id': row[12],
                    'name': row[13],
                    'resx': row[14],
                    'resy': row[15],
                    'pixel_x': row[16],
                    'pixel_y': row[17],
                    'bits': row[18],
                    'width': row[19],
                    'height': row[20]
                }
            else:
                telescope['sensor'] = None

            telescopes.append(telescope)

        return {"telescopes": telescopes}


@blp.route("/catalogs/search")
class ObjectSearchResource(MethodView):
    @jwt_required()
    @blp.arguments(ObjectSearchRequestSchema, location="query")
    @blp.response(200, ObjectSearchResponseSchema)
    def get(self, args):
        """Search for astronomical objects by name
        Returns a list of objects matching the search query
        """
        query = args['query']
        limit = args['limit']

        # Build the search query
        search_query = """
            SELECT object_id, name, ra, decl, descr, comment, type, epoch, const,
                   magn, x, y, altname, distance, catalog
            FROM objects
            WHERE name ILIKE %s OR altname ILIKE %s
            ORDER BY name
            LIMIT %s
        """

        # Add wildcards for partial matching
        search_pattern = f"%{query}%"

        cnx = db.connect()
        results = db.run_query(cnx, search_query, (search_pattern, search_pattern, limit))
        cnx.close()

        # Format the results
        objects = []
        for row in results:
            obj = {
                'object_id': row[0],
                'name': row[1],
                'ra': row[2],
                'decl': row[3],
                'descr': row[4],
                'comment': row[5],
                'type': row[6],
                'epoch': row[7],
                'const': row[8],
                'magn': row[9],
                'x': row[10],
                'y': row[11],
                'altname': row[12],
                'distance': row[13],
                'catalog': row[14]
            }
            objects.append(obj)

        return {"objects": objects}


@blp.route("/catalogs/list")
class ObjectsListResource(MethodView):
    @jwt_required()
    @blp.arguments(ObjectsListRequestSchema, location="query")
    @blp.response(200, ObjectsListResponseSchema)
    def get(self, args):
        """Get list of astronomical objects with paging, sorting, and filtering"""
        return self._get_objects(args)

    @jwt_required()
    @blp.arguments(ObjectsListRequestSchema)
    @blp.response(200, ObjectsListResponseSchema)
    def post(self, args):
        """Get list of astronomical objects with paging, sorting, and filtering"""
        return self._get_objects(args)

    def _get_objects(self, args):
        """Helper method to get objects based on filters, sorting, and paging"""
        # Base query
        query = """
            SELECT object_id, name, ra, decl, descr, comment, type, epoch, const,
                   magn, x, y, altname, distance, catalog
            FROM objects
        """

        count_query = "SELECT COUNT(*) FROM objects"

        # Build where clause and parameters
        where_clauses = []
        params = []

        # Apply filters
        if args.get('catalog'):
            where_clauses.append("catalog ILIKE %s")
            params.append(args['catalog'])

        if args.get('constellation'):
            where_clauses.append("const ILIKE %s")
            params.append(args['constellation'])

        if args.get('name'):
            where_clauses.append("name ILIKE %s")
            params.append(f"%{args['name']}%")

        # Add where clauses to queries
        if where_clauses:
            where_str = " WHERE " + " AND ".join(where_clauses)
            query += where_str
            count_query += where_str

        # Add sorting
        sort_field = args.get('sort_by', 'name')
        sort_order = args.get('sort_order', 'asc').upper()
        query += f" ORDER BY {sort_field} {sort_order}"

        # Add pagination
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page
        query += f" LIMIT {per_page} OFFSET {offset}"

        # Execute queries
        cnx = db.connect()

        # Get total count
        total_count = db.run_query(cnx, count_query, params)[0][0]

        # Get paginated results
        objects_list = db.run_query(cnx, query, params)
        cnx.close()

        logger.info(
            "Catalog list: returned %d entries (page %d, total matching: %d)",
            len(objects_list), page, total_count
        )

        # Format objects
        formatted_objects = []
        for obj in objects_list:
            obj_dict = {
                'object_id': obj[0],
                'name': obj[1],
                'ra': obj[2],
                'decl': obj[3],
                'descr': obj[4],
                'comment': obj[5],
                'type': obj[6],
                'epoch': obj[7],
                'const': obj[8],
                'magn': obj[9],
                'x': obj[10],
                'y': obj[11],
                'altname': obj[12],
                'distance': obj[13],
                'catalog': obj[14]
            }
            formatted_objects.append(obj_dict)

        # Calculate total pages
        total_pages = (total_count + per_page - 1) // per_page

        return {
            "objects": formatted_objects,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages
        }


# Register blueprint
api.register_blueprint(blp)


if __name__ == '__main__':
    app.run()
