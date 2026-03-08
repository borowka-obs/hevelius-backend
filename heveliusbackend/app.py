"""
Flask application that provides a REST API to the Hevelius backend.
"""

import logging
import os
from flask import Flask, render_template, request

from flask_cors import CORS
from flask_smorest import Api, Blueprint, abort
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

# Load OpenAPI spec from YAML (api/openapi.yaml at project root)
dir_path = os.path.dirname(os.path.realpath(__file__))
_project_root = os.path.dirname(dir_path)

with open(os.path.join(_project_root, 'api', 'openapi.yaml')) as f:
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
    project_ids = fields.List(fields.Integer(), metadata={"description": "Project IDs this task belongs to"})


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
    vendor = fields.String(metadata={"description": "Sensor/camera vendor"})
    url = fields.String(metadata={"description": "URL for sensor info"})
    active = fields.Boolean(metadata={"description": "Whether the sensor is active"})


class SensorCreateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(max=128))
    resx = fields.Integer(required=True)
    resy = fields.Integer(required=True)
    pixel_x = fields.Float(required=True)
    pixel_y = fields.Float(required=True)
    bits = fields.Integer(load_default=0)
    width = fields.Float(load_default=None)
    height = fields.Float(load_default=None)
    vendor = fields.String(validate=validate.Length(max=128), load_default=None)
    url = fields.String(validate=validate.Length(max=512), load_default=None)
    active = fields.Boolean(load_default=True)


class SensorUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(max=128), load_default=None)
    resx = fields.Integer(load_default=None)
    resy = fields.Integer(load_default=None)
    pixel_x = fields.Float(load_default=None)
    pixel_y = fields.Float(load_default=None)
    bits = fields.Integer(load_default=None)
    width = fields.Float(load_default=None)
    height = fields.Float(load_default=None)
    vendor = fields.String(validate=validate.Length(max=128), load_default=None)
    url = fields.String(validate=validate.Length(max=512), load_default=None)
    active = fields.Boolean(load_default=None)


class FilterSchema(Schema):
    filter_id = fields.Integer(required=True, metadata={"description": "Filter primary key"})
    short_name = fields.String(metadata={"description": "Short name"})
    full_name = fields.String(metadata={"description": "Full filter name"})
    url = fields.String(metadata={"description": "URL for filter info"})
    active = fields.Boolean(metadata={"description": "Whether the filter is active"})


class FilterCreateSchema(Schema):
    short_name = fields.String(required=True, validate=validate.Length(max=8), metadata={"description": "Short name (e.g. SG, CV)"})
    full_name = fields.String(validate=validate.Length(max=256), load_default=None)
    url = fields.String(validate=validate.Length(max=512), load_default=None)
    active = fields.Boolean(load_default=True)


class FilterUpdateSchema(Schema):
    short_name = fields.String(validate=validate.Length(max=8), load_default=None)
    full_name = fields.String(validate=validate.Length(max=256), load_default=None)
    url = fields.String(validate=validate.Length(max=512), load_default=None)
    active = fields.Boolean(load_default=None)


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
    filters = fields.List(fields.Nested(FilterSchema), metadata={"description": "Filters on this telescope"})
    active = fields.Boolean(metadata={"description": "Whether the telescope is active"})


class TelescopesListSchema(Schema):
    telescopes = fields.List(fields.Nested(TelescopeSchema))


class ScopeCreateSchema(Schema):
    scope_id = fields.Integer(load_default=None)
    name = fields.String(required=True, validate=validate.Length(max=64))
    descr = fields.String(validate=validate.Length(max=1024))
    min_dec = fields.Float()
    max_dec = fields.Float()
    focal = fields.Float()
    aperture = fields.Float()
    lon = fields.Float()
    lat = fields.Float()
    alt = fields.Float()
    sensor_id = fields.Integer(load_default=None)
    active = fields.Boolean(load_default=True)


class ScopeUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(max=64))
    descr = fields.String(validate=validate.Length(max=1024))
    min_dec = fields.Float()
    max_dec = fields.Float()
    focal = fields.Float()
    aperture = fields.Float()
    lon = fields.Float()
    lat = fields.Float()
    alt = fields.Float()
    sensor_id = fields.Integer(load_default=None)
    active = fields.Boolean()


class ProjectSubframeSchema(Schema):
    id = fields.Integer()
    project_id = fields.Integer()
    filter_id = fields.Integer()
    filter = fields.Nested(FilterSchema, allow_none=True)
    exposure_time = fields.Float()
    count = fields.Integer()
    active = fields.Boolean()


class ProjectSchema(Schema):
    project_id = fields.Integer()
    name = fields.String()
    description = fields.String()
    ra = fields.Float()
    decl = fields.Float()
    active = fields.Boolean()
    subframes = fields.List(fields.Nested(ProjectSubframeSchema))
    user_ids = fields.List(fields.Integer())


class ProjectsListSchema(Schema):
    projects = fields.List(fields.Nested(ProjectSchema))
    total = fields.Integer()
    page = fields.Integer()
    per_page = fields.Integer()
    pages = fields.Integer()


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
                'sent': bool(task[32]),
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


def _scopes_base_query():
    return """
        SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
               t.lon, t.lat, t.alt, t.sensor_id, t.active,
               s.sensor_id, s.name, s.resx, s.resy, s.pixel_x, s.pixel_y,
               s.bits, s.width, s.height, s.vendor, s.url, s.active AS sensor_active
        FROM telescopes t
        LEFT JOIN sensors s ON t.sensor_id = s.sensor_id
    """


def _fetch_filters_for_scopes(cnx, scope_ids):
    if not scope_ids:
        return {}
    placeholders = ",".join(["%s"] * len(scope_ids))
    tf_query = f"""
        SELECT tf.scope_id, f.filter_id, f.short_name, f.full_name, f.url, f.active
        FROM telescope_filters tf
        JOIN filters f ON tf.filter_id = f.filter_id
        WHERE tf.scope_id IN ({placeholders})
        ORDER BY tf.scope_id, f.filter_id
    """
    tf_rows = db.run_query(cnx, tf_query, scope_ids)
    out = {}
    for r in (tf_rows or []):
        sid = r[0]
        if sid not in out:
            out[sid] = []
        out[sid].append({'filter_id': r[1], 'short_name': r[2], 'full_name': r[3], 'url': r[4], 'active': r[5]})
    return out


@blp.route("/scopes")
class ScopesResource(MethodView):
    @jwt_required()
    @blp.arguments(Schema.from_dict({
        "sort_by": fields.String(load_default="scope_id"),
        "sort_order": fields.String(load_default="asc")
    }), location="query")
    @blp.response(200, TelescopesListSchema)
    def get(self, args):
        """Get list of telescopes with their associated sensors and filters. Supports sorting."""
        sort_by = args.get("sort_by") or "scope_id"
        sort_order = (args.get("sort_order") or "asc").upper()
        if sort_by not in ("scope_id", "name", "focal", "active"):
            sort_by = "scope_id"
        if sort_order not in ("ASC", "DESC"):
            sort_order = "ASC"
        order_col = "t.scope_id" if sort_by == "scope_id" else f"t.{sort_by}"
        query = _scopes_base_query() + f" ORDER BY {order_col} {sort_order}"
        cnx = db.connect()
        results = db.run_query(cnx, query)
        scope_ids = [r[0] for r in (results or [])]
        telescope_filters = _fetch_filters_for_scopes(cnx, scope_ids)
        cnx.close()
        telescopes = [_telescope_row_to_dict(row, telescope_filters.get(row[0], [])) for row in (results or [])]
        return {"telescopes": telescopes}

    @jwt_required()
    @blp.arguments(ScopeCreateSchema)
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "scope_id": fields.Integer(),
        "scope": fields.Nested(TelescopeSchema),
        "msg": fields.String()
    }))
    def post(self, data):
        """Add new telescope. name required; scope_id optional (auto-assigned if omitted)."""
        name = data["name"]
        scope_id = data.get("scope_id")
        sensor_id = data.get("sensor_id")
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
                return {"status": False, "scope_id": None, "scope": None, "msg": f"Telescope scope_id={scope_id} already exists"}
        cols = ["scope_id", "name"]
        vals = [scope_id, name]
        for key in ("descr", "min_dec", "max_dec", "focal", "aperture", "lon", "lat", "alt", "active"):
            if data.get(key) is not None:
                cols.append(key)
                vals.append(data[key])
        if sensor_id is not None:
            cols.append("sensor_id")
            vals.append(sensor_id)
        placeholders = ", ".join(["%s"] * len(vals))
        try:
            db.run_query(cnx, f"INSERT INTO telescopes ({', '.join(cols)}) VALUES ({placeholders})", vals)
        except Exception as e:
            cnx.close()
            return {"status": False, "scope_id": None, "scope": None, "msg": str(e)}
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, [])) if row else {
            "scope_id": scope_id, "name": name, "descr": data.get("descr"), "min_dec": data.get("min_dec"),
            "max_dec": data.get("max_dec"), "focal": data.get("focal"), "aperture": data.get("aperture"),
            "lon": data.get("lon"), "lat": data.get("lat"), "alt": data.get("alt"), "sensor": None,
            "filters": [], "active": data.get("active", True)
        }
        return {"status": True, "scope_id": scope_id, "scope": scope, "msg": "Created"}


@blp.route("/scopes/<int:scope_id>")
class ScopeDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({"status": fields.Boolean(), "scope": fields.Nested(TelescopeSchema), "msg": fields.String()}))
    def get(self, scope_id):
        """Get telescope details with sensor and filters."""
        cnx = db.connect()
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        if not row:
            cnx.close()
            return {"status": False, "scope": None, "msg": f"Telescope scope_id={scope_id} not found"}
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, []))
        return {"status": True, "scope": scope, "msg": "OK"}

    @jwt_required()
    @blp.arguments(ScopeUpdateSchema)
    @blp.response(200, Schema.from_dict({"status": fields.Boolean(), "scope": fields.Nested(TelescopeSchema), "msg": fields.String()}))
    def patch(self, data, scope_id):
        """Edit telescope. Use sensor_id 0 to remove sensor."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
        if not row:
            cnx.close()
            return {"status": False, "scope": None, "msg": f"Telescope scope_id={scope_id} not found"}
        updates = []
        params = []
        for key in ("name", "descr", "min_dec", "max_dec", "focal", "aperture", "lon", "lat", "alt", "active"):
            if data.get(key) is not None:
                updates.append(f"{key} = %s")
                params.append(data[key])
        if "sensor_id" in data:
            sid = data["sensor_id"]
            updates.append("sensor_id = %s")
            params.append(None if sid == 0 else sid)
        if updates:
            params.append(scope_id)
            db.run_query(cnx, "UPDATE telescopes SET " + ", ".join(updates) + " WHERE scope_id = %s", tuple(params))
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, [])) if row else None
        return {"status": True, "scope": scope, "msg": "Updated"}


@blp.route("/scopes/<int:scope_id>/filters")
class ScopeFiltersResource(MethodView):
    @jwt_required()
    @blp.arguments(Schema.from_dict({"filter_id": fields.Integer(required=True)}))
    @blp.response(200, Schema.from_dict({"status": fields.Boolean(), "msg": fields.String()}))
    def post(self, data, scope_id):
        """Add filter to telescope."""
        filter_id = data["filter_id"]
        cnx = db.connect()
        scope = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
        flt = db.run_query(cnx, "SELECT filter_id FROM filters WHERE filter_id = %s", (filter_id,))
        if not scope or not flt:
            cnx.close()
            return {"status": False, "msg": "Telescope or filter not found"}
        try:
            db.run_query(cnx, "INSERT INTO telescope_filters (scope_id, filter_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (scope_id, filter_id))
        except Exception as e:
            cnx.close()
            return {"status": False, "msg": str(e)}
        cnx.close()
        return {"status": True, "msg": "Filter added"}


@blp.route("/scopes/<int:scope_id>/filters/<int:filter_id>")
class ScopeFilterRemoveResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({"status": fields.Boolean(), "msg": fields.String()}))
    def delete(self, scope_id, filter_id):
        """Remove filter from telescope."""
        cnx = db.connect()
        db.run_query(cnx, "DELETE FROM telescope_filters WHERE scope_id = %s AND filter_id = %s", (scope_id, filter_id))
        cnx.close()
        return {"status": True, "msg": "Filter removed"}


def _row_to_filter(r):
    return {"filter_id": r[0], "short_name": r[1], "full_name": r[2], "url": r[3], "active": r[4]}


def _telescope_row_to_dict(row, filters_list=None):
    """Build telescope dict from main query row (t + s columns). filters_list is optional."""
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
        'active': row[11],
        'filters': filters_list or []
    }
    if row[10] is not None:  # sensor_id
        telescope['sensor'] = {
            'sensor_id': row[12], 'name': row[13], 'resx': row[14], 'resy': row[15],
            'pixel_x': row[16], 'pixel_y': row[17], 'bits': row[18],
            'width': row[19], 'height': row[20],
            'vendor': row[21], 'url': row[22], 'active': row[23]
        }
    else:
        telescope['sensor'] = None
    return telescope


@blp.route("/filters")
class FiltersResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({"filters": fields.List(fields.Nested(FilterSchema))}))
    def get(self):
        """Get list of filters. Sortable by filter_id, short_name, full_name, active (default filter_id)."""
        active = request.args.get("active", type=lambda v: v.lower() == "true" if isinstance(v, str) else None)
        sort_by = request.args.get("sort_by", "filter_id")
        sort_order = (request.args.get("sort_order") or "asc").upper()
        if sort_by not in ("filter_id", "short_name", "full_name", "active"):
            sort_by = "filter_id"
        if sort_order not in ("ASC", "DESC"):
            sort_order = "ASC"
        query = "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE 1=1"
        params = []
        if active is not None:
            query += " AND active = %s"
            params.append(active)
        query += f" ORDER BY {sort_by} {sort_order}"
        cnx = db.connect()
        rows = db.run_query(cnx, query, params if params else None)
        cnx.close()
        filters_list = [_row_to_filter(r) for r in (rows or [])]
        return {"filters": filters_list}

    @jwt_required()
    @blp.arguments(FilterCreateSchema)
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "filter_id": fields.Integer(),
        "filter": fields.Nested(FilterSchema),
        "msg": fields.String()
    }))
    def post(self, filter_data):
        """Add new filter"""
        short_name = filter_data["short_name"]
        full_name = filter_data.get("full_name")
        url = filter_data.get("url")
        active = filter_data.get("active", True)
        cnx = db.connect()
        try:
            row = db.run_query(
                cnx,
                "INSERT INTO filters (short_name, full_name, url, active) VALUES (%s, %s, %s, %s) RETURNING filter_id",
                (short_name, full_name, url, active)
            )
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Filter with this short_name already exists.")
            raise
        filter_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if filter_id is None:
            abort(500, message="Failed to create filter.")
        # Fetch the created row
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        if not rows:
            abort(500, message="Filter created but could not be retrieved.")
        return {
            "status": True,
            "filter_id": filter_id,
            "filter": _row_to_filter(rows[0]),
            "msg": "Filter created successfully."
        }


@blp.route("/filters/<int:filter_id>")
class FilterDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "filter": fields.Nested(FilterSchema),
        "msg": fields.String()
    }))
    def get(self, filter_id):
        """Get single filter"""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        if not rows:
            abort(404, message="Filter not found.")
        return {"status": True, "filter": _row_to_filter(rows[0]), "msg": "OK"}

    @jwt_required()
    @blp.arguments(FilterUpdateSchema)
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "filter": fields.Nested(FilterSchema),
        "msg": fields.String()
    }))
    def patch(self, filter_data, filter_id):
        """Edit filter (partial update). Set active true/false to activate or deactivate."""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        if not rows:
            cnx.close()
            abort(404, message="Filter not found.")
        updates = []
        params = []
        for key in ("short_name", "full_name", "url", "active"):
            if key in filter_data and filter_data[key] is not None:
                updates.append(f"{key} = %s")
                params.append(filter_data[key])
        if not updates:
            cnx.close()
            return {"status": True, "filter": _row_to_filter(rows[0]), "msg": "No changes."}
        params.append(filter_id)
        try:
            db.run_query(cnx, "UPDATE filters SET " + ", ".join(updates) + " WHERE filter_id = %s", tuple(params))
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Filter with this short_name already exists.")
            raise
        updated = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        return {"status": True, "filter": _row_to_filter(updated[0]), "msg": "Filter updated."}


SENSOR_SORT_FIELDS = {"sensor_id", "name", "resx", "resy", "pixel_x", "pixel_y", "width", "height", "vendor"}


def _round2(val):
    """Round to 2 decimal places for display; None stays None."""
    return round(val, 2) if val is not None else None


def _row_to_sensor(r):
    return {
        "sensor_id": r[0], "name": r[1], "resx": r[2], "resy": r[3],
        "pixel_x": r[4], "pixel_y": r[5], "bits": r[6],
        "width": _round2(r[7]), "height": _round2(r[8]),
        "vendor": r[9], "url": r[10], "active": r[11]
    }


@blp.route("/sensors")
class SensorsResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({"sensors": fields.List(fields.Nested(SensorSchema))}))
    def get(self):
        """Get list of sensors (cameras) with optional sorting"""
        active = request.args.get("active", type=lambda v: v.lower() == "true" if isinstance(v, str) else None)
        sort_by = request.args.get("sort_by", "sensor_id")
        sort_order = request.args.get("sort_order", "asc")
        if sort_by not in SENSOR_SORT_FIELDS:
            sort_by = "sensor_id"
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"
        query = """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                   FROM sensors WHERE 1=1"""
        params = []
        if active is not None:
            query += " AND active = %s"
            params.append(active)
        query += f" ORDER BY {sort_by} {sort_order}"
        cnx = db.connect()
        rows = db.run_query(cnx, query, params if params else None)
        cnx.close()
        sensors_list = [_row_to_sensor(r) for r in (rows or [])]
        return {"sensors": sensors_list}

    @jwt_required()
    @blp.arguments(SensorCreateSchema)
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "sensor_id": fields.Integer(),
        "sensor": fields.Nested(SensorSchema),
        "msg": fields.String()
    }))
    def post(self, sensor_data):
        """Add new sensor. width/height computed from resx*px/1000 if not provided. bits defaults to 0."""
        name = sensor_data["name"]
        resx = sensor_data["resx"]
        resy = sensor_data["resy"]
        pixel_x = sensor_data["pixel_x"]
        pixel_y = sensor_data["pixel_y"]
        bits = sensor_data.get("bits") if sensor_data.get("bits") is not None else 0
        width = sensor_data.get("width")
        height = sensor_data.get("height")
        if width is None:
            width = round(resx * pixel_x / 1000.0, 2)
        else:
            width = round(width, 2)
        if height is None:
            height = round(resy * pixel_y / 1000.0, 2)
        else:
            height = round(height, 2)
        cnx = db.connect()
        row = db.run_query(
            cnx,
            """INSERT INTO sensors (name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING sensor_id""",
            (
                name,
                resx,
                resy,
                pixel_x,
                pixel_y,
                bits,
                width,
                height,
                sensor_data.get("vendor"),
                sensor_data.get("url"),
                sensor_data.get("active", True),
            )
        )
        sensor_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if sensor_id is None:
            abort(500, message="Failed to create sensor.")
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                        vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        if not rows:
            abort(500, message="Sensor created but could not be retrieved.")
        return {
            "status": True,
            "sensor_id": sensor_id,
            "sensor": _row_to_sensor(rows[0]),
            "msg": "Sensor created successfully."
        }


@blp.route("/sensors/<int:sensor_id>")
class SensorDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "sensor": fields.Nested(SensorSchema),
        "msg": fields.String()
    }))
    def get(self, sensor_id):
        """Get single sensor"""
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                       vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        if not rows:
            abort(404, message="Sensor not found.")
        return {"status": True, "sensor": _row_to_sensor(rows[0]), "msg": "OK"}

    @jwt_required()
    @blp.arguments(SensorUpdateSchema)
    @blp.response(200, Schema.from_dict({
        "status": fields.Boolean(),
        "sensor": fields.Nested(SensorSchema),
        "msg": fields.String()
    }))
    def patch(self, sensor_data, sensor_id):
        """Edit sensor (partial update)"""
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                       vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        if not rows:
            cnx.close()
            abort(404, message="Sensor not found.")
        updates = []
        params = []
        for key in ("name", "resx", "resy", "pixel_x", "pixel_y", "bits", "width", "height", "vendor", "url", "active"):
            if key in sensor_data and sensor_data[key] is not None:
                updates.append(f"{key} = %s")
                params.append(sensor_data[key])
        if not updates:
            cnx.close()
            return {"status": True, "sensor": _row_to_sensor(rows[0]), "msg": "No changes."}
        params.append(sensor_id)
        db.run_query(cnx, "UPDATE sensors SET " + ", ".join(updates) + " WHERE sensor_id = %s", tuple(params))
        updated = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                         vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        return {"status": True, "sensor": _row_to_sensor(updated[0]), "msg": "Sensor updated."}


@blp.route("/projects")
class ProjectsResource(MethodView):
    @jwt_required()
    @blp.response(200, ProjectsListSchema)
    def get(self):
        """Get list of projects with paging"""
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 100, type=int), 1000)
        user_id = request.args.get("user_id", type=int)
        offset = (page - 1) * per_page
        cnx = db.connect()
        if user_id is not None:
            count_q = "SELECT COUNT(*) FROM projects p JOIN project_users pu ON p.project_id = pu.project_id WHERE pu.user_id = %s"
            list_q = """SELECT p.project_id, p.name, p.description, p.ra, p.decl, p.active
                       FROM projects p JOIN project_users pu ON p.project_id = pu.project_id
                       WHERE pu.user_id = %s ORDER BY p.project_id LIMIT %s OFFSET %s"""
            total = db.run_query(cnx, count_q, (user_id,))[0][0]
            rows = db.run_query(cnx, list_q, (user_id, per_page, offset))
        else:
            count_q = "SELECT COUNT(*) FROM projects"
            list_q = "SELECT project_id, name, description, ra, decl, active FROM projects ORDER BY project_id LIMIT %s OFFSET %s"
            total = db.run_query(cnx, count_q)[0][0]
            rows = db.run_query(cnx, list_q, (per_page, offset))
        projects = []
        for r in (rows or []):
            pid, name, descr, ra, decl, active = r[0], r[1], r[2], r[3], r[4], r[5]
            sub_q = """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                       ps.exposure_time, ps.count, ps.active FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id WHERE ps.project_id = %s"""
            sub_rows = db.run_query(cnx, sub_q, (pid,))
            user_q = "SELECT user_id FROM project_users WHERE project_id = %s"
            user_rows = db.run_query(cnx, user_q, (pid,))
            subframes = [
                {
                    "id": sr[0], "project_id": sr[1], "filter_id": sr[2],
                    "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
                    "exposure_time": sr[8], "count": sr[9], "active": sr[10]
                }
                for sr in (sub_rows or [])
            ]
            user_ids = [ur[0] for ur in (user_rows or [])]
            projects.append({
                "project_id": pid, "name": name, "description": descr, "ra": ra, "decl": decl, "active": active,
                "subframes": subframes, "user_ids": user_ids
            })
        cnx.close()
        pages = (total + per_page - 1) // per_page if total else 0
        return {"projects": projects, "total": total, "page": page, "per_page": per_page, "pages": pages}


@blp.route("/projects/<int:project_id>")
class ProjectDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, Schema.from_dict({"status": fields.Boolean(), "project": fields.Nested(ProjectSchema), "msg": fields.String()}))
    def get(self, project_id):
        """Get single project with subframes and user IDs"""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT project_id, name, description, ra, decl, active FROM projects WHERE project_id = %s", (project_id,))
        if not row:
            cnx.close()
            return {"status": False, "project": None, "msg": f"Project {project_id} not found"}
        r = row[0]
        sub_q = """SELECT ps.id, ps.project_id, ps.filter_id, f.filter_id, f.short_name, f.full_name, f.url, f.active,
                   ps.exposure_time, ps.count, ps.active FROM project_subframes ps JOIN filters f ON ps.filter_id = f.filter_id WHERE ps.project_id = %s"""
        sub_rows = db.run_query(cnx, sub_q, (project_id,))
        user_rows = db.run_query(cnx, "SELECT user_id FROM project_users WHERE project_id = %s", (project_id,))
        cnx.close()
        subframes = [
            {
                "id": sr[0], "project_id": sr[1], "filter_id": sr[2],
                "filter": {"filter_id": sr[3], "short_name": sr[4], "full_name": sr[5], "url": sr[6], "active": sr[7]},
                "exposure_time": sr[8], "count": sr[9], "active": sr[10]
            }
            for sr in (sub_rows or [])
        ]
        user_ids = [ur[0] for ur in (user_rows or [])]
        project = {
            "project_id": r[0], "name": r[1], "description": r[2], "ra": r[3], "decl": r[4], "active": r[5],
            "subframes": subframes, "user_ids": user_ids
        }
        return {"status": True, "project": project, "msg": "OK"}


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
