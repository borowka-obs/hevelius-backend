"""
Flask application that provides a REST API to the Hevelius backend.
"""

import difflib
import logging
import hashlib
import hmac
import os
import re
import secrets
from flask import Flask, render_template, request

from flask_cors import CORS
from flask_smorest import Api, Blueprint, abort
import yaml
import json
import plotly
from marshmallow import Schema, fields, ValidationError, validate, validates_schema
from flask.views import MethodView
from datetime import date, datetime, timedelta, timezone
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
from argon2 import PasswordHasher, Type  # type: ignore[import-not-found]
from argon2.exceptions import VerifyMismatchError, InvalidHashError  # type: ignore[import-not-found]

from astropy.coordinates import EarthLocation
from astropy import units as u

from hevelius import cmd_asteroid, cmd_stats, db, config as hevelius_config
from hevelius.user_admin_audit import log_user_admin_action
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


def _normalize_jwt_secret(secret: str) -> str:
    # PyJWT>=2.10 warns for HS256 keys shorter than 32 bytes.
    # Derive a stable 32-byte equivalent from legacy short secrets.
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < 32:
        return hashlib.sha256(secret_bytes).hexdigest()
    return secret


app.config["JWT_SECRET_KEY"] = _normalize_jwt_secret(jwt_secret)
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
jwt = JWTManager(app)


@jwt.user_identity_loader
def _jwt_identity_to_string(identity):
    # PyJWT>=2.10 requires "sub" (subject) claim to be a string.
    return str(identity)


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
        metadata={"description": "Password (plaintext, sent over HTTPS)"}
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
    msg = fields.String()


# `password` in /api/login is plaintext. Legacy DB values may still be MD5 hex;
# those are verified once and immediately replaced with argon2id.
password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # KiB
    parallelism=1,
    type=Type.ID,
)

_MD5_HEX_RE = re.compile(r"^[a-fA-F0-9]{32}$")

PASSWORD_RESET_TOKEN_TTL = timedelta(hours=1)


def _password_reset_token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _jwt_user_id_int():
    ident = get_jwt_identity()
    try:
        return int(ident)
    except (TypeError, ValueError):
        return None


def _escape_sql_like_suffix_pattern(filename: str) -> str:
    """Build LIKE pattern for paths ending with filename; escape %, _, \\ for ESCAPE E'\\\\'."""
    escaped = (
        filename.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return "%" + escaped


class TaskAddRequestSchema(Schema):
    user_id = fields.Integer(
        required=True,
        metadata={"description": "User ID"}
    )
    scope_id = fields.Integer(
        metadata={"description": "Scope ID"}
    )
    state = fields.Integer(
        validate=validate.OneOf([0, 1, 6], error="State must be one of 0, 1, or 6"),
        load_default=1,  # Default to 1 if not specified
        metadata={"description": "Task state (0 - disabled, 1 - new, 6 - done)"}
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
    imagename = fields.String(
        metadata={"description": "Image filename"}
    )
    filter_id = fields.Integer(
        metadata={"description": "Filter ID (resolved to filter short_name)"}
    )
    project_id = fields.Integer(
        metadata={"description": "Single project ID alias"}
    )
    project_ids = fields.List(
        fields.Integer(),
        load_default=lambda: [],
        metadata={"description": "Project IDs this task belongs to (default: none)"}
    )

    @validates_schema
    def validate_cross_fields(self, data, **kwargs):
        if data.get("filter") and data.get("filter_id") is not None:
            raise ValidationError("Provide either filter or filter_id, not both", field_name="filter_id")
        if data.get("project_id") is not None and data.get("project_ids"):
            raise ValidationError("Provide either project_id or project_ids, not both", field_name="project_id")
        if data.get("state") == 6 and not data.get("imagename"):
            raise ValidationError("imagename is required when state is 6 (done)", field_name="imagename")


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
    project_id = fields.Integer(metadata={"description": "Filter by project ID (tasks assigned to this project)"})
    performed_after = fields.DateTime(metadata={"description": "Filter tasks performed after this time"})
    performed_before = fields.DateTime(metadata={"description": "Filter tasks performed before this time"})


class Task(Schema):
    task_id = fields.Integer(required=True, metadata={"description": "Task ID"})
    user_id = fields.Integer(required=True, metadata={"description": "User ID"})
    user_login = fields.String(allow_none=True, metadata={"description": "Task owner login"})
    scope_id = fields.Integer(required=True, metadata={"description": "Telescope ID"})
    scope_name = fields.String(allow_none=True, metadata={"description": "Telescope name"})
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


class TaskFindByFilenameQuerySchema(Schema):
    filename = fields.String(
        required=True,
        validate=validate.Length(min=1, max=256),
        metadata={"description": "Filename suffix to match against stored path (API name; DB column imagename)"},
    )


class TaskFindByFilenameMatchItem(Schema):
    task_id = fields.Integer(required=True)
    filename = fields.String(
        allow_none=True,
        metadata={"description": "Stored path (DB imagename)"},
    )


class TaskFindByFilenameResponseSchema(Schema):
    found = fields.Boolean(required=True)
    matches = fields.List(fields.Nested(TaskFindByFilenameMatchItem), required=True)


class TasksFilenameListQuerySchema(Schema):
    page = fields.Integer(missing=1, validate=validate.Range(min=1))
    per_page = fields.Integer(
        missing=2000,
        validate=validate.Range(min=1, max=5000),
        metadata={"description": "Rows per page (max 5000)"},
    )


class TasksFilenameListResponseSchema(Schema):
    rows = fields.List(
        fields.Tuple((fields.Integer(), fields.String(allow_none=True))),
        required=True,
        metadata={"description": "Compact [task_id, filename] rows"},
    )
    total = fields.Integer(required=True)
    page = fields.Integer(required=True)
    per_page = fields.Integer(required=True)
    pages = fields.Integer(required=True)


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
    state = fields.Integer(
        validate=validate.OneOf([0, 1, 6], error="State must be one of 0, 1, or 6"),
        metadata={"description": "Task state (0 - disabled, 1 - new, 6 - done)"}
    )
    imagename = fields.String(metadata={"description": "Image filename"})
    filter_id = fields.Integer(metadata={"description": "Filter ID (resolved to filter short_name)"})
    project_id = fields.Integer(metadata={"description": "Single project ID alias"})
    project_ids = fields.List(
        fields.Integer(),
        metadata={"description": "Project IDs this task belongs to (replaces current list when provided)"}
    )

    @validates_schema
    def validate_cross_fields(self, data, **kwargs):
        if data.get("filter") and data.get("filter_id") is not None:
            raise ValidationError("Provide either filter or filter_id, not both", field_name="filter_id")
        if data.get("project_id") is not None and data.get("project_ids"):
            raise ValidationError("Provide either project_id or project_ids, not both", field_name="project_id")


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
    default_rotation = fields.Float(
        allow_none=True,
        metadata={"description": "Default camera rotation (degrees East of North) applied to new projects on this telescope when not specified"}
    )


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
    default_rotation = fields.Float(
        load_default=None, allow_none=True,
        metadata={"description": "Default camera rotation (degrees East of North) for new projects on this telescope"}
    )


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
    default_rotation = fields.Float(allow_none=True)


class ProjectSubframeSchema(Schema):
    id = fields.Integer()
    project_id = fields.Integer()
    filter_id = fields.Integer()
    filter = fields.Nested(FilterSchema, allow_none=True)
    exposure_time = fields.Float()
    count = fields.Integer()
    goal_count = fields.Integer()
    active = fields.Boolean()
    last_updated = fields.DateTime(allow_none=True)


class ProjectSchema(Schema):
    project_id = fields.Integer()
    name = fields.String()
    description = fields.String()
    regexps = fields.String(allow_none=True)
    scope_id = fields.Integer()
    ra = fields.Float()
    decl = fields.Float()
    active = fields.Boolean()
    last_updated = fields.DateTime(allow_none=True)
    total_integration_time = fields.Float()
    start_date = fields.String(allow_none=True)
    end_date = fields.String(allow_none=True)
    publications = fields.String(allow_none=True)
    rotation = fields.Float(allow_none=True)
    focal = fields.Float(allow_none=True, metadata={"description": "Focal length (mm) at time of project creation"})
    resx = fields.Integer(allow_none=True, metadata={"description": "Sensor width (pixels)"})
    resy = fields.Integer(allow_none=True, metadata={"description": "Sensor height (pixels)"})
    pixel_x = fields.Float(allow_none=True, metadata={"description": "Pixel pitch X (µm)"})
    pixel_y = fields.Float(allow_none=True, metadata={"description": "Pixel pitch Y (µm)"})
    subframes = fields.List(fields.Nested(ProjectSubframeSchema))
    user_ids = fields.List(fields.Integer())


class ProjectCreateSchema(Schema):
    name = fields.String(required=True)
    scope_id = fields.Integer(required=True)
    description = fields.String(load_default="")
    regexps = fields.String(load_default=None)
    ra = fields.Float(load_default=None)
    decl = fields.Float(load_default=None)
    active = fields.Boolean(load_default=True)
    start_date = fields.Date(load_default=None, allow_none=True)
    end_date = fields.Date(load_default=None, allow_none=True)
    publications = fields.String(load_default=None, allow_none=True)
    rotation = fields.Float(load_default=None, allow_none=True)
    focal = fields.Float(load_default=None, allow_none=True)
    resx = fields.Integer(load_default=None, allow_none=True)
    resy = fields.Integer(load_default=None, allow_none=True)
    pixel_x = fields.Float(load_default=None, allow_none=True)
    pixel_y = fields.Float(load_default=None, allow_none=True)


class ProjectUpdateSchema(Schema):
    name = fields.String()
    description = fields.String()
    regexps = fields.String(allow_none=True)
    scope_id = fields.Integer()
    ra = fields.Float()
    decl = fields.Float()
    active = fields.Boolean()
    start_date = fields.Date(allow_none=True)
    end_date = fields.Date(allow_none=True)
    publications = fields.String(allow_none=True)
    rotation = fields.Float(allow_none=True)
    focal = fields.Float(allow_none=True)
    resx = fields.Integer(allow_none=True)
    resy = fields.Integer(allow_none=True)
    pixel_x = fields.Float(allow_none=True)
    pixel_y = fields.Float(allow_none=True)


class ProjectSubframeCreateSchema(Schema):
    filter = fields.String(load_default=None)  # short name; mutually exclusive with filter_id
    filter_id = fields.Integer(load_default=None)
    exposure_time = fields.Float(required=True)
    count = fields.Integer(load_default=None)
    goal_count = fields.Integer(load_default=None)
    active = fields.Boolean(load_default=True)


class ProjectSubframeUpdateSchema(Schema):
    filter = fields.String(load_default=None)  # short name; mutually exclusive with filter_id
    filter_id = fields.Integer(load_default=None)
    exposure_time = fields.Float()
    count = fields.Integer()
    goal_count = fields.Integer()
    active = fields.Boolean()


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


class InstalledCatalogSchema(Schema):
    name = fields.String(required=True, metadata={"description": "Catalog name"})
    shortname = fields.String(required=True, metadata={"description": "Catalog short name"})
    object_count = fields.Integer(required=True, metadata={"description": "Number of objects in this catalog"})


class CatalogsInstalledRequestSchema(Schema):
    sort = fields.String(
        missing='entries',
        validate=validate.OneOf(['entries', 'name']),
        metadata={"description": "Sort by object count (entries) or catalog name (name)"},
    )


class CatalogsInstalledResponseSchema(Schema):
    catalogs = fields.List(fields.Nested(InstalledCatalogSchema))


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
    name = fields.String(metadata={"description": "Filter by object name (matches name or altname)"})
    ra = fields.Float(metadata={"description": "Right ascension in hours; requires decl"})
    decl = fields.Float(metadata={"description": "Declination in degrees; requires ra"})
    proximity = fields.Float(
        missing=1.0,
        validate=validate.Range(min=0.0),
        metadata={"description": "Search radius in degrees when ra and decl are set"},
    )

    @validates_schema
    def validate_ra_decl_pair(self, data, **_kwargs):
        has_ra = data.get('ra') is not None
        has_decl = data.get('decl') is not None
        if has_ra != has_decl:
            raise ValidationError('ra and decl must both be specified or both omitted')


class ObjectsListResponseSchema(Schema):
    objects = fields.List(fields.Nested(ObjectSchema))
    total = fields.Integer(required=True, metadata={"description": "Total number of objects"})
    page = fields.Integer(required=True, metadata={"description": "Current page number"})
    per_page = fields.Integer(required=True, metadata={"description": "Items per page"})
    pages = fields.Integer(required=True, metadata={"description": "Total number of pages"})


class ObjectSearchResponseSchema(Schema):
    objects = fields.List(fields.Nested(ObjectSchema))


class AsteroidTagSchema(Schema):
    tag_id = fields.Integer(required=True, metadata={"description": "Tag ID"})
    name = fields.String(required=True, metadata={"description": "Tag name (e.g. amor, neo, pha)"})
    description = fields.String(allow_none=True, metadata={"description": "Tag description"})
    color = fields.String(allow_none=True, metadata={"description": "Display color (e.g. #1976d2)"})
    asteroid_count = fields.Integer(metadata={"description": "Number of asteroids carrying this tag"})


class AsteroidTagCreateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=64),
                         metadata={"description": "Tag name (e.g. amor, neo, pha)"})
    description = fields.String(validate=validate.Length(max=256), load_default=None, allow_none=True)
    color = fields.String(validate=validate.Length(max=16), load_default=None, allow_none=True)


class AsteroidTagUpdateSchema(Schema):
    name = fields.String(validate=validate.Length(min=1, max=64), load_default=None)
    description = fields.String(validate=validate.Length(max=256), load_default=None, allow_none=True)
    color = fields.String(validate=validate.Length(max=16), load_default=None, allow_none=True)


class AsteroidTagsListResponseSchema(Schema):
    tags = fields.List(fields.Nested(AsteroidTagSchema))


class AsteroidTagCreateResponseSchema(Schema):
    status = fields.Boolean()
    tag_id = fields.Integer()
    tag = fields.Nested(AsteroidTagSchema)
    msg = fields.String()


class AsteroidTagDetailResponseSchema(Schema):
    status = fields.Boolean()
    tag = fields.Nested(AsteroidTagSchema)
    msg = fields.String()


class AsteroidTagAttachRequestSchema(Schema):
    tag_id = fields.Integer(required=True, metadata={"description": "Tag ID to attach"})


class AsteroidSchema(Schema):
    asteroid_id = fields.Integer(required=True, metadata={"description": "Asteroid ID"})
    number = fields.Integer(allow_none=True, metadata={"description": "MPC number (null for unnumbered/provisional objects)"})
    designation = fields.String(required=True, metadata={"description": "Packed MPC designation"})
    epoch = fields.String(metadata={"description": "Epoch in MPC packed format"})
    mean_anomaly = fields.Float(metadata={"description": "Mean anomaly M at epoch (degrees)"})
    perihelion_arg = fields.Float(metadata={"description": "Argument of perihelion omega (degrees)"})
    ascending_node = fields.Float(metadata={"description": "Longitude of ascending node Omega (degrees)"})
    inclination = fields.Float(metadata={"description": "Orbital inclination i (degrees)"})
    eccentricity = fields.Float(metadata={"description": "Eccentricity e"})
    mean_motion = fields.Float(metadata={"description": "Mean daily motion n (degrees/day)"})
    semimajor_axis = fields.Float(metadata={"description": "Semi-major axis a (AU)"})
    absolute_magnitude = fields.Float(allow_none=True, metadata={"description": "Absolute magnitude H"})
    slope_parameter = fields.Float(allow_none=True, metadata={"description": "Phase slope parameter G"})
    tags = fields.List(fields.Nested(AsteroidTagSchema), metadata={"description": "Tags attached to this asteroid"})


class AsteroidsListRequestSchema(Schema):
    # Paging parameters
    page = fields.Integer(missing=1, validate=validate.Range(min=1),
                          metadata={"description": "Page number (starting from 1)"})
    per_page = fields.Integer(missing=100, validate=validate.Range(min=1, max=1000),
                              metadata={"description": "Number of items per page"})

    # Sorting parameters
    sort_by = fields.String(missing='number', validate=validate.OneOf(
        ['number', 'designation', 'absolute_magnitude', 'semimajor_axis',
         'eccentricity', 'inclination', 'mean_motion', 'epoch'],
        error="Invalid sort field. Must be one of: number, designation, absolute_magnitude, "
              "semimajor_axis, eccentricity, inclination, mean_motion, epoch"
    ))
    sort_order = fields.String(missing='asc', validate=validate.OneOf(['asc', 'desc']),
                               metadata={"description": "Sort order (asc or desc)"})

    # Filtering parameters
    designation = fields.String(metadata={"description": "Filter by designation (partial match)"})
    number = fields.Integer(metadata={"description": "Filter by exact MPC number"})
    numbered = fields.Boolean(metadata={"description": "true: only numbered asteroids; false: only unnumbered/provisional"})
    mag_min = fields.Float(metadata={"description": "Minimum absolute magnitude (H)"})
    mag_max = fields.Float(metadata={"description": "Maximum absolute magnitude (H)"})
    tags = fields.String(metadata={"description": "Comma-separated tag names to filter by (e.g. 'neo,pha')"})
    tags_mode = fields.String(
        missing='any', validate=validate.OneOf(['any', 'all']),
        metadata={"description": "'any' (default) matches at least one listed tag; 'all' requires every listed tag"}
    )

    @validates_schema
    def validate_mag_range(self, data, **_kwargs):
        mag_min = data.get('mag_min')
        mag_max = data.get('mag_max')
        if mag_min is not None and mag_max is not None and mag_min > mag_max:
            raise ValidationError('mag_min must be less than or equal to mag_max')


class AsteroidsListResponseSchema(Schema):
    asteroids = fields.List(fields.Nested(AsteroidSchema))
    total = fields.Integer(required=True, metadata={"description": "Total number of asteroids"})
    page = fields.Integer(required=True, metadata={"description": "Current page number"})
    per_page = fields.Integer(required=True, metadata={"description": "Items per page"})
    pages = fields.Integer(required=True, metadata={"description": "Total number of pages"})


class AsteroidDetailResponseSchema(Schema):
    status = fields.Boolean()
    asteroid = fields.Nested(AsteroidSchema)
    msg = fields.String()


class AsteroidVisibilityQuerySchema(Schema):
    scope_id = fields.Integer(required=True, metadata={"description": "Telescope to compute visibility from"})
    date = fields.Date(
        load_default=None,
        metadata={"description": "Evening date (YYYY-MM-DD) whose night to compute; defaults to tonight"}
    )
    step_minutes = fields.Integer(
        load_default=10, validate=validate.Range(min=1, max=120),
        metadata={"description": "Sampling interval across the night, in minutes"}
    )


class AsteroidVisibilitySampleSchema(Schema):
    time = fields.String(metadata={"description": "Sample time (UTC)"})
    altitude_deg = fields.Float(metadata={"description": "Altitude above the horizon (degrees)"})
    azimuth_deg = fields.Float(metadata={"description": "Azimuth (degrees, from North through East)"})
    apparent_magnitude = fields.Float(allow_none=True, metadata={"description": "Estimated apparent magnitude, if H is known"})


class AsteroidVisibilityResponseSchema(Schema):
    status = fields.Boolean()
    scope_id = fields.Integer()
    scope_name = fields.String()
    night_start = fields.String(metadata={"description": "Start of the astronomical night (UTC)"})
    night_end = fields.String(metadata={"description": "End of the astronomical night (UTC)"})
    samples = fields.List(fields.Nested(AsteroidVisibilitySampleSchema))
    max_altitude_deg = fields.Float(metadata={"description": "Highest altitude reached during the night"})
    max_altitude_time = fields.String(metadata={"description": "Time of highest altitude (UTC)"})
    apparent_magnitude_at_max = fields.Float(allow_none=True)
    visible = fields.Boolean(metadata={"description": "Whether the asteroid rises above the horizon during the night"})
    has_magnitude_estimate = fields.Boolean(metadata={"description": "Whether absolute_magnitude (H) was available"})
    msg = fields.String()


class PasswordResetCompleteBodySchema(Schema):
    token = fields.String(required=True, metadata={"description": "One-time reset token"})
    new_password = fields.String(
        required=True,
        validate=validate.Length(min=8, error="Password must be at least 8 characters"),
        metadata={"description": "New password"},
    )


class StatusMsgSchema(Schema):
    status = fields.Boolean()
    msg = fields.String()


class TaskGetQuerySchema(Schema):
    task_id = fields.Integer(required=True)


class ScopesListQuerySchema(Schema):
    sort_by = fields.String(load_default="scope_id")
    sort_order = fields.String(load_default="asc")


class ScopeCreateResponseSchema(Schema):
    status = fields.Boolean()
    scope_id = fields.Integer()
    scope = fields.Nested(TelescopeSchema)
    msg = fields.String()


class ScopeDetailResponseSchema(Schema):
    status = fields.Boolean()
    scope = fields.Nested(TelescopeSchema)
    msg = fields.String()


class ScopeFilterIdBodySchema(Schema):
    filter_id = fields.Integer(required=True)


class FiltersListResponseSchema(Schema):
    filters = fields.List(fields.Nested(FilterSchema))


class FilterCreateResponseSchema(Schema):
    status = fields.Boolean()
    filter_id = fields.Integer()
    filter = fields.Nested(FilterSchema)
    msg = fields.String()


class FilterDetailResponseSchema(Schema):
    status = fields.Boolean()
    filter = fields.Nested(FilterSchema)
    msg = fields.String()


class SensorsListResponseSchema(Schema):
    sensors = fields.List(fields.Nested(SensorSchema))


class SensorCreateResponseSchema(Schema):
    status = fields.Boolean()
    sensor_id = fields.Integer()
    sensor = fields.Nested(SensorSchema)
    msg = fields.String()


class SensorDetailResponseSchema(Schema):
    status = fields.Boolean()
    sensor = fields.Nested(SensorSchema)
    msg = fields.String()


class ProjectDetailResponseSchema(Schema):
    status = fields.Boolean()
    project = fields.Nested(ProjectSchema)
    msg = fields.String()


class PasswordResetTokenIssueResponseSchema(Schema):
    status = fields.Boolean()
    token = fields.String(metadata={"description": "Plain token; shown only once"})
    expires_at = fields.DateTime(metadata={"description": "Token expiry (UTC)"})
    user_id = fields.Integer()
    msg = fields.String()


class UserLoginMapEntrySchema(Schema):
    user_id = fields.Integer(metadata={"description": "User ID"})
    login = fields.String(allow_none=True, metadata={"description": "Login name"})


class UsersLoginsResponseSchema(Schema):
    users = fields.List(fields.Nested(UserLoginMapEntrySchema))


class UserAdminDetailSchema(Schema):
    user_id = fields.Integer()
    login = fields.String(allow_none=True)
    firstname = fields.String(allow_none=True)
    lastname = fields.String(allow_none=True)
    share = fields.Float(allow_none=True)
    phone = fields.String(allow_none=True)
    email = fields.String(allow_none=True)
    permissions = fields.Integer()
    aavso_id = fields.String(allow_none=True)
    login_enabled = fields.Boolean(metadata={"description": "True if pass_d is set"})


class UsersAdminListResponseSchema(Schema):
    users = fields.List(fields.Nested(UserAdminDetailSchema))


class UserProfileUpdateSchema(Schema):
    firstname = fields.String(allow_none=True, validate=validate.Length(max=32))
    lastname = fields.String(allow_none=True, validate=validate.Length(max=32))
    email = fields.String(allow_none=True, validate=validate.Length(max=64))
    aavso_id = fields.String(allow_none=True, validate=validate.Length(max=5))


class UserPasswordChangeSchema(Schema):
    current_password = fields.String(required=True, metadata={"description": "Current password"})
    new_password = fields.String(
        required=True,
        validate=validate.Length(min=8, error="Password must be at least 8 characters"),
        metadata={"description": "New password"},
    )


class AuditLogEntrySchema(Schema):
    id = fields.Integer()
    created_at = fields.DateTime()
    channel = fields.String()
    actor_user_id = fields.Integer(allow_none=True)
    action = fields.String()
    target_user_id = fields.Integer(allow_none=True)
    details = fields.Raw(allow_none=True)


class UsersAuditLogResponseSchema(Schema):
    entries = fields.List(fields.Nested(AuditLogEntrySchema))
    total = fields.Integer()
    page = fields.Integer()
    per_page = fields.Integer()
    pages = fields.Integer()


def _jwt_permissions_int():
    claims = get_jwt()
    p = claims.get("permissions")
    if p is None:
        return 0
    try:
        return int(p)
    except (TypeError, ValueError):
        return 0


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
        password = login_data.get('password')

        if user is None:
            return {'status': False, 'msg': 'Username not provided'}
        if password is None:
            return {'status': False, 'msg': 'Password not provided'}

        query = """SELECT user_id, pass_d, login, firstname, lastname, share, phone, email, permissions,
                aavso_id FROM users WHERE login=%s"""

        cnx = db.connect()
        db_resp = db.run_query(cnx, query, (user,))
        cnx.close()

        if db_resp is None or not len(db_resp):
            print(f"Login: No such username ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        user_id, pass_db, _, firstname, lastname, share, phone, email, permissions, aavso_id = db_resp[0]

        # Legacy: `pass_d` stored as MD5 hex (case-insensitive). Upgrade to argon2id lazily
        # after successful login.
        if pass_db is None:
            print(f"Login: Missing pass_d for user ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        if isinstance(pass_db, str) and _MD5_HEX_RE.fullmatch(pass_db):
            legacy_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(legacy_md5.lower(), pass_db.lower()):
                print(f"Login: Invalid legacy MD5 password for user ({user})")
                return {'status': False, 'msg': 'Invalid credentials'}

            # Successful legacy verification: replace with argon2id hash.
            pass_d_new = password_hasher.hash(password)
            cnx = db.connect()
            db.run_query(cnx, "UPDATE users SET pass_d=%s WHERE user_id=%s", (pass_d_new, user_id))
            cnx.close()
        else:
            # New format: argon2id hash string (stored format is self-describing).
            if not (isinstance(pass_db, str) and pass_db.startswith("$argon2")):
                print(f"Login: Unsupported pass_d format for user ({user})")
                return {'status': False, 'msg': 'Invalid credentials'}

            try:
                password_hasher.verify(pass_db, password)
            except (VerifyMismatchError, InvalidHashError):
                print(f"Login: Invalid argon2id password for user ({user})")
                return {'status': False, 'msg': 'Invalid credentials'}

            # Future re-hashing: upgrade transparently if params are weak/changed.
            try:
                if password_hasher.check_needs_rehash(pass_db):
                    pass_d_new = password_hasher.hash(password)
                    cnx = db.connect()
                    db.run_query(cnx, "UPDATE users SET pass_d=%s WHERE user_id=%s", (pass_d_new, user_id))
                    cnx.close()
            except InvalidHashError:
                print(f"Login: Invalid argon2id hash for user ({user})")
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
        return _login_success_payload(
            access_token, user_id, firstname, lastname, share, phone, email,
            permissions, aavso_id, user,
        )


def _login_success_payload(access_token, user_id, firstname, lastname, share, phone, email,
                           permissions, aavso_id, username):
    return {
        'status': True,
        'token': access_token,
        'user_id': user_id,
        'firstname': firstname,
        'lastname': lastname,
        'share': share,
        'phone': phone,
        'email': email,
        'permissions': permissions,
        'aavso_id': aavso_id,
        'msg': 'Welcome'
    }


@blp.route("/login/refresh")
class LoginRefreshResource(MethodView):
    @jwt_required()
    @blp.response(200, LoginResponseSchema)
    def post(self):
        """Issue a new access token for the current user (extends session on activity)."""
        user_id = get_jwt_identity()
        claims = get_jwt()
        access_token = create_access_token(
            identity=user_id,
            additional_claims={
                'permissions': claims.get('permissions'),
                'username': claims.get('username'),
            },
        )
        return {'status': True, 'token': access_token, 'user_id': int(user_id), 'msg': 'Token refreshed'}


@blp.route("/auth/password-reset")
class AuthPasswordResetResource(MethodView):
    @blp.arguments(PasswordResetCompleteBodySchema)
    @blp.response(200, StatusMsgSchema)
    def post(self, body):
        """Apply password reset using a token issued by an administrator."""
        token_hash = _password_reset_token_hash(body["token"])
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT id, user_id FROM password_reset_tokens
               WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now()""",
            (token_hash,),
        )
        if not rows:
            cnx.close()
            return {"status": False, "msg": "Invalid or expired reset token"}
        rid, user_id = rows[0]
        new_hash = password_hasher.hash(body["new_password"])
        db.run_query(cnx, "UPDATE users SET pass = NULL, pass_d = %s WHERE user_id = %s", (new_hash, user_id))
        db.run_query(
            cnx,
            "UPDATE password_reset_tokens SET consumed_at = now() WHERE id = %s",
            (rid,),
        )
        cnx.close()
        log_user_admin_action(
            "api",
            "auth.password_reset_complete",
            actor_user_id=None,
            target_user_id=user_id,
            details={},
        )
        return {"status": True, "msg": "Password updated"}


@blp.route("/users/me")
class UsersMeResource(MethodView):
    @jwt_required()
    @blp.response(200, UserAdminDetailSchema)
    def get(self):
        """Current user profile (from JWT); no password fields."""
        uid = _jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email, permissions,
                      aavso_id, pass_d
               FROM users WHERE user_id = %s""",
            (uid,),
        )
        cnx.close()
        if not rows:
            abort(404, message="User not found")
        r = rows[0]
        row_uid, login, fn, ln, share, phone, email, perm, aavso, pass_d = r
        return {
            "user_id": row_uid,
            "login": login,
            "firstname": fn,
            "lastname": ln,
            "share": float(share) if share is not None else None,
            "phone": phone,
            "email": email,
            "permissions": perm,
            "aavso_id": aavso,
            "login_enabled": bool(pass_d and str(pass_d).strip()),
        }

    @jwt_required()
    @blp.arguments(UserProfileUpdateSchema, location="json")
    @blp.response(200, UserAdminDetailSchema)
    def patch(self, body):
        """Update own profile: firstname, lastname, email (optional, may be empty), aavso_id."""
        uid = _jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        if not db.run_query(cnx, "SELECT user_id FROM users WHERE user_id = %s", (uid,)):
            cnx.close()
            abort(404, message="User not found")
        updates = []
        args = []
        for key in ("firstname", "lastname", "aavso_id"):
            if key in body:
                updates.append(f"{key} = %s")
                args.append(body[key] or None)
        if "email" in body:
            updates.append("email = %s")
            args.append(body["email"] if body["email"] else None)
        if updates:
            args.append(uid)
            db.run_query(cnx, "UPDATE users SET " + ", ".join(updates) + " WHERE user_id = %s", tuple(args))
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email,
                      permissions, aavso_id, pass_d
               FROM users WHERE user_id = %s""",
            (uid,),
        )
        cnx.close()
        r = rows[0]
        return {
            "user_id": r[0], "login": r[1], "firstname": r[2], "lastname": r[3],
            "share": float(r[4]) if r[4] is not None else None,
            "phone": r[5], "email": r[6], "permissions": r[7], "aavso_id": r[8],
            "login_enabled": bool(r[9] and str(r[9]).strip()),
        }


@blp.route("/users/me/password")
class UsersMePasswordResource(MethodView):
    @jwt_required()
    @blp.arguments(UserPasswordChangeSchema, location="json")
    @blp.response(200, StatusMsgSchema)
    def post(self, body):
        """Change own password. current_password must match the stored credential."""
        uid = _jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT pass_d FROM users WHERE user_id = %s", (uid,))
        cnx.close()
        if not rows:
            abort(404, message="User not found")
        pass_d = rows[0][0]
        if not (pass_d and str(pass_d).strip()):
            abort(400, message="Account has no password set; use the password reset flow.")
        current = body["current_password"]
        if isinstance(pass_d, str) and _MD5_HEX_RE.fullmatch(pass_d):
            abort(400, message="Legacy password format detected; use the password reset flow.")
        elif isinstance(pass_d, str) and pass_d.startswith("$argon2"):
            try:
                password_hasher.verify(pass_d, current)
            except (VerifyMismatchError, InvalidHashError):
                abort(400, message="Current password is incorrect.")
        else:
            abort(400, message="Unsupported password format; use the password reset flow.")
        new_hash = password_hasher.hash(body["new_password"])
        cnx = db.connect()
        db.run_query(cnx, "UPDATE users SET pass = NULL, pass_d = %s WHERE user_id = %s", (new_hash, uid))
        cnx.close()
        log_user_admin_action("api", "user.password_change", actor_user_id=uid, target_user_id=uid, details={})
        return {"status": True, "msg": "Password updated"}


@blp.route("/users/audit-log")
class UsersAuditLogResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersAuditLogResponseSchema)
    def get(self):
        """Recent user-administration audit entries (administrators only)."""
        if (_jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(500, max(1, int(request.args.get("per_page", 50))))
        offset = (page - 1) * per_page
        cnx = db.connect()
        total = db.run_query(cnx, "SELECT count(*) FROM user_admin_audit")[0][0]
        rows = db.run_query(
            cnx,
            """SELECT id, created_at, channel, actor_user_id, action, target_user_id, details
               FROM user_admin_audit ORDER BY id DESC LIMIT %s OFFSET %s""",
            (per_page, offset),
        )
        cnx.close()
        entries = []
        for row in rows or []:
            rid, created_at, channel, actor_uid, action, target_uid, details = row
            entries.append({
                "id": rid,
                "created_at": created_at,
                "channel": channel,
                "actor_user_id": actor_uid,
                "action": action,
                "target_user_id": target_uid,
                "details": details if isinstance(details, dict) else None,
            })
        pages = (total + per_page - 1) // per_page if total else 0
        return {
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }


@blp.route("/users/logins")
class UsersLoginsResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersLoginsResponseSchema)
    def get(self):
        """Compact user_id → login mapping for any authenticated user."""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT user_id, login FROM users ORDER BY user_id")
        cnx.close()
        users = [{"user_id": r[0], "login": r[1]} for r in (rows or [])]
        return {"users": users}


@blp.route("/users/<int:user_id>/password-reset-token")
class UserPasswordResetTokenResource(MethodView):
    @jwt_required()
    @blp.response(200, PasswordResetTokenIssueResponseSchema)
    def post(self, user_id):
        """Issue a one-time password reset token for a user (administrators only)."""
        if (_jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not row:
            cnx.close()
            abort(404, message="User not found")
        db.run_query(
            cnx,
            "DELETE FROM password_reset_tokens WHERE user_id = %s AND consumed_at IS NULL",
            (user_id,),
        )
        raw = secrets.token_urlsafe(32)
        th = _password_reset_token_hash(raw)
        expires_at = datetime.now(timezone.utc) + PASSWORD_RESET_TOKEN_TTL
        db.run_query(
            cnx,
            """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
               VALUES (%s, %s, %s)""",
            (user_id, th, expires_at),
        )
        cnx.close()
        actor = _jwt_user_id_int()
        log_user_admin_action(
            "api",
            "users.password_reset_token_issue",
            actor_user_id=actor,
            target_user_id=user_id,
            details={},
        )
        return {
            "status": True,
            "token": raw,
            "expires_at": expires_at,
            "user_id": user_id,
            "msg": "Deliver this token to the user securely; it is not stored in plaintext.",
        }


@blp.route("/users")
class UsersAdminListResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersAdminListResponseSchema)
    def get(self):
        """Full user list without passwords; requires permissions bit 0 (administrator)."""
        if (_jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        log_user_admin_action(
            "api",
            "users.list_full",
            actor_user_id=_jwt_user_id_int(),
            target_user_id=None,
            details={},
        )
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email, permissions,
                      aavso_id, pass_d
               FROM users ORDER BY user_id""",
        )
        cnx.close()
        users = []
        for r in rows or []:
            uid, login, fn, ln, share, phone, email, perm, aavso, pass_d = r
            users.append({
                "user_id": uid,
                "login": login,
                "firstname": fn,
                "lastname": ln,
                "share": float(share) if share is not None else None,
                "phone": phone,
                "email": email,
                "permissions": perm,
                "aavso_id": aavso,
                "login_enabled": bool(pass_d and str(pass_d).strip()),
            })
        return {"users": users}


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
        if (task_data['user_id'] != current_user_id) and not app.testing:
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


def _scopes_base_query():
    return """
        SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
               t.lon, t.lat, t.alt, t.sensor_id, t.active, t.default_rotation,
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
    @blp.arguments(ScopesListQuerySchema, location="query")
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
    @blp.response(200, ScopeCreateResponseSchema)
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
        for key in ("descr", "min_dec", "max_dec", "focal", "aperture", "lon", "lat", "alt", "active", "default_rotation"):
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
            "filters": [], "active": data.get("active", True), "default_rotation": data.get("default_rotation")
        }
        return {"status": True, "scope_id": scope_id, "scope": scope, "msg": "Created"}


@blp.route("/scopes/<int:scope_id>")
class ScopeDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, ScopeDetailResponseSchema)
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
    @blp.response(200, ScopeDetailResponseSchema)
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
        if "default_rotation" in data:
            updates.append("default_rotation = %s")
            params.append(data["default_rotation"])   # None is valid — clears the value
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
    @blp.arguments(ScopeFilterIdBodySchema)
    @blp.response(200, StatusMsgSchema)
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
    @blp.response(200, StatusMsgSchema)
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
        'default_rotation': row[12],
        'filters': filters_list or []
    }
    if row[10] is not None:  # sensor_id
        telescope['sensor'] = {
            'sensor_id': row[13], 'name': row[14], 'resx': row[15], 'resy': row[16],
            'pixel_x': row[17], 'pixel_y': row[18], 'bits': row[19],
            'width': row[20], 'height': row[21],
            'vendor': row[22], 'url': row[23], 'active': row[24]
        }
    else:
        telescope['sensor'] = None
    return telescope


@blp.route("/filters")
class FiltersResource(MethodView):
    @jwt_required()
    @blp.response(200, FiltersListResponseSchema)
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
    @blp.response(200, FilterCreateResponseSchema)
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
    @blp.response(200, FilterDetailResponseSchema)
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
    @blp.response(200, FilterDetailResponseSchema)
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
    @blp.response(200, SensorsListResponseSchema)
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
    @blp.response(200, SensorCreateResponseSchema)
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
    @blp.response(200, SensorDetailResponseSchema)
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
    @blp.response(200, SensorDetailResponseSchema)
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
    """Return list of existing projects whose names are similar to name (substring or fuzzy match)."""
    if exclude_id is not None:
        rows = db.run_query(cnx, "SELECT project_id, name FROM projects WHERE project_id != %s", (exclude_id,))
    else:
        rows = db.run_query(cnx, "SELECT project_id, name FROM projects")
    if not rows:
        return []
    name_lower = name.strip().lower()
    similar = []
    for r in rows:
        pid, pname = r[0], r[1]
        pname_lower = (pname or "").strip().lower()
        if name_lower in pname_lower or pname_lower in name_lower:
            similar.append({"project_id": pid, "name": pname})
            continue
        if difflib.SequenceMatcher(None, name_lower, pname_lower).ratio() >= 0.6:
            similar.append({"project_id": pid, "name": pname})
    return similar


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


def _object_row_to_dict(row):
    return {
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
        'catalog': row[14],
    }


@blp.route("/catalogs")
class CatalogsInstalledResource(MethodView):
    @jwt_required()
    @blp.arguments(CatalogsInstalledRequestSchema, location="query")
    @blp.response(200, CatalogsInstalledResponseSchema)
    def get(self, args):
        """List installed catalogs with object counts."""
        sort_by = args.get('sort', 'entries')
        sort_order = 'desc' if sort_by == 'entries' else 'asc'
        cnx = db.connect()
        rows = db.catalogs_installed_list(cnx, sort_by=sort_by, sort_order=sort_order)
        cnx.close()
        return {
            'catalogs': [
                {'name': row[0], 'shortname': row[1], 'object_count': row[2]}
                for row in rows
            ],
        }


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

        return {"objects": [_object_row_to_dict(row) for row in results]}


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
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page

        cnx = db.connect()
        total_count = db.catalog_objects_count(
            cnx,
            catalog=args.get('catalog'),
            constellation=args.get('constellation'),
            name=args.get('name'),
            ra_hours=args.get('ra'),
            decl=args.get('decl'),
            proximity=args.get('proximity', 1.0),
        )
        objects_list = db.catalog_objects_search(
            cnx,
            catalog=args.get('catalog'),
            constellation=args.get('constellation'),
            name=args.get('name'),
            ra_hours=args.get('ra'),
            decl=args.get('decl'),
            proximity=args.get('proximity', 1.0),
            sort_by=args.get('sort_by', 'name'),
            sort_order=args.get('sort_order', 'asc'),
            limit=per_page,
            offset=offset,
        )
        cnx.close()

        logger.info(
            "Catalog list: returned %d entries (page %d, total matching: %d)",
            len(objects_list), page, total_count
        )

        total_pages = (total_count + per_page - 1) // per_page if per_page else 0

        return {
            "objects": [_object_row_to_dict(obj) for obj in objects_list],
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages,
        }


def _asteroid_row_to_dict(row, tags=None):
    (asteroid_id, number, designation, epoch, mean_anomaly, perihelion_arg,
     ascending_node, inclination, eccentricity, mean_motion, semimajor_axis,
     absolute_magnitude, slope_parameter) = row
    return {
        'asteroid_id': asteroid_id,
        'number': number,
        'designation': designation,
        'epoch': epoch,
        'mean_anomaly': mean_anomaly,
        'perihelion_arg': perihelion_arg,
        'ascending_node': ascending_node,
        'inclination': inclination,
        'eccentricity': eccentricity,
        'mean_motion': mean_motion,
        'semimajor_axis': semimajor_axis,
        'absolute_magnitude': absolute_magnitude,
        'slope_parameter': slope_parameter,
        'tags': tags or [],
    }


def _parse_tag_names(raw: str):
    if not raw:
        return None
    names = [n.strip() for n in raw.split(',') if n.strip()]
    return names or None


def _row_to_asteroid_tag(row):
    tag_id, name, description, color, asteroid_count = row
    return {
        'tag_id': tag_id, 'name': name, 'description': description,
        'color': color, 'asteroid_count': asteroid_count,
    }


@blp.route("/asteroids")
class AsteroidsListResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidsListRequestSchema, location="query")
    @blp.response(200, AsteroidsListResponseSchema)
    def get(self, args):
        """Get list of asteroids with paging, sorting, and filtering"""
        return self._get_asteroids(args)

    @jwt_required()
    @blp.arguments(AsteroidsListRequestSchema)
    @blp.response(200, AsteroidsListResponseSchema)
    def post(self, args):
        """Get list of asteroids with paging, sorting, and filtering"""
        return self._get_asteroids(args)

    def _get_asteroids(self, args):
        """Helper method to get asteroids based on filters, sorting, and paging"""
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page
        tag_names = _parse_tag_names(args.get('tags'))
        tags_mode = args.get('tags_mode', 'any')

        cnx = db.connect()
        total_count = db.asteroids_count(
            cnx,
            designation=args.get('designation'),
            number=args.get('number'),
            numbered=args.get('numbered'),
            mag_min=args.get('mag_min'),
            mag_max=args.get('mag_max'),
            tag_names=tag_names,
            tags_mode=tags_mode,
        )
        asteroids_list = db.asteroids_search(
            cnx,
            designation=args.get('designation'),
            number=args.get('number'),
            numbered=args.get('numbered'),
            mag_min=args.get('mag_min'),
            mag_max=args.get('mag_max'),
            tag_names=tag_names,
            tags_mode=tags_mode,
            sort_by=args.get('sort_by', 'number'),
            sort_order=args.get('sort_order', 'asc'),
            limit=per_page,
            offset=offset,
        )
        tags_by_asteroid = db.asteroid_tags_for_asteroids(cnx, [row[0] for row in asteroids_list])
        cnx.close()

        logger.info(
            "Asteroid list: returned %d entries (page %d, total matching: %d)",
            len(asteroids_list), page, total_count
        )

        total_pages = (total_count + per_page - 1) // per_page if per_page else 0

        return {
            "asteroids": [
                _asteroid_row_to_dict(row, tags=tags_by_asteroid.get(row[0]))
                for row in asteroids_list
            ],
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages,
        }


@blp.route("/asteroids/<int:asteroid_id>")
class AsteroidDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, AsteroidDetailResponseSchema)
    def get(self, asteroid_id):
        """Get single asteroid by ID"""
        cnx = db.connect()
        row = db.asteroid_get_by_id(cnx, asteroid_id)
        if row is None:
            cnx.close()
            abort(404, message="Asteroid not found.")
        tags = db.asteroid_tags_for_asteroids(cnx, [asteroid_id]).get(asteroid_id)
        cnx.close()
        return {"status": True, "asteroid": _asteroid_row_to_dict(row, tags=tags), "msg": "OK"}


@blp.route("/asteroids/<int:asteroid_id>/visibility")
class AsteroidVisibilityResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidVisibilityQuerySchema, location="query")
    @blp.response(200, AsteroidVisibilityResponseSchema)
    def get(self, args, asteroid_id):
        """
        Compute altitude/azimuth/magnitude across a night for one asteroid as
        seen from a telescope's location. Defaults to tonight; pass `date` to
        check a different night. The orbital mechanics live in
        hevelius.cmd_asteroid so the same computation can be reused by a
        future CLI command.
        """
        cnx = db.connect()
        asteroid_row = db.asteroid_get_by_id(cnx, asteroid_id)
        if asteroid_row is None:
            cnx.close()
            abort(404, message="Asteroid not found.")

        scope_id = args["scope_id"]
        scope_rows = db.run_query(
            cnx, "SELECT name, lat, lon, alt FROM telescopes WHERE scope_id = %s", (scope_id,)
        )
        cnx.close()
        if not scope_rows:
            abort(404, message="Telescope not found.")
        scope_name, lat, lon, alt = scope_rows[0]
        if lat is None or lon is None:
            abort(400, message="Telescope has no location (lat/lon) configured.")

        obs_date = args.get("date") or date.today()
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=(alt or 0) * u.m)

        result = cmd_asteroid.compute_asteroid_visibility_curve(
            asteroid_row[1:], location, obs_date.isoformat(), step_minutes=args.get("step_minutes", 10),
        )

        return {
            "status": True,
            "scope_id": scope_id,
            "scope_name": scope_name,
            **result,
            "msg": "OK",
        }


@blp.route("/asteroid-tags")
class AsteroidTagsResource(MethodView):
    @jwt_required()
    @blp.response(200, AsteroidTagsListResponseSchema)
    def get(self):
        """List all asteroid tags, with the number of asteroids carrying each."""
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT t.tag_id, t.name, t.description, t.color, COUNT(m.asteroid_id)
               FROM asteroid_tags t
               LEFT JOIN asteroid_tag_map m ON m.tag_id = t.tag_id
               GROUP BY t.tag_id
               ORDER BY t.name""",
        )
        cnx.close()
        return {"tags": [_row_to_asteroid_tag(r) for r in (rows or [])]}

    @jwt_required()
    @blp.arguments(AsteroidTagCreateSchema)
    @blp.response(200, AsteroidTagCreateResponseSchema)
    def post(self, tag_data):
        """Create a new asteroid tag (e.g. amor, neo, pha, fast rotator)."""
        cnx = db.connect()
        try:
            row = db.run_query(
                cnx,
                "INSERT INTO asteroid_tags (name, description, color) VALUES (%s, %s, %s) RETURNING tag_id",
                (tag_data["name"], tag_data.get("description"), tag_data.get("color")),
            )
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Tag with this name already exists.")
            raise
        tag_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if tag_id is None:
            abort(500, message="Failed to create tag.")
        return {
            "status": True,
            "tag_id": tag_id,
            "tag": {
                "tag_id": tag_id, "name": tag_data["name"],
                "description": tag_data.get("description"), "color": tag_data.get("color"),
                "asteroid_count": 0,
            },
            "msg": "Tag created successfully.",
        }


@blp.route("/asteroid-tags/<int:tag_id>")
class AsteroidTagDetailResource(MethodView):
    def _fetch(self, cnx, tag_id):
        rows = db.run_query(
            cnx,
            """SELECT t.tag_id, t.name, t.description, t.color, COUNT(m.asteroid_id)
               FROM asteroid_tags t
               LEFT JOIN asteroid_tag_map m ON m.tag_id = t.tag_id
               WHERE t.tag_id = %s
               GROUP BY t.tag_id""",
            (tag_id,),
        )
        return rows[0] if rows else None

    @jwt_required()
    @blp.response(200, AsteroidTagDetailResponseSchema)
    def get(self, tag_id):
        """Get a single asteroid tag."""
        cnx = db.connect()
        row = self._fetch(cnx, tag_id)
        cnx.close()
        if row is None:
            abort(404, message="Tag not found.")
        return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "OK"}

    @jwt_required()
    @blp.arguments(AsteroidTagUpdateSchema)
    @blp.response(200, AsteroidTagDetailResponseSchema)
    def patch(self, tag_data, tag_id):
        """Edit an asteroid tag (partial update: name, description, color)."""
        cnx = db.connect()
        if self._fetch(cnx, tag_id) is None:
            cnx.close()
            abort(404, message="Tag not found.")
        updates = []
        params = []
        for key in ("name", "description", "color"):
            if key in tag_data and tag_data[key] is not None:
                updates.append(f"{key} = %s")
                params.append(tag_data[key])
        if not updates:
            row = self._fetch(cnx, tag_id)
            cnx.close()
            return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "No changes."}
        params.append(tag_id)
        try:
            db.run_query(cnx, "UPDATE asteroid_tags SET " + ", ".join(updates) + " WHERE tag_id = %s", tuple(params))
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Tag with this name already exists.")
            raise
        row = self._fetch(cnx, tag_id)
        cnx.close()
        return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "Tag updated."}

    @jwt_required()
    @blp.response(200, StatusMsgSchema)
    def delete(self, tag_id):
        """Delete an asteroid tag (also removes it from any tagged asteroids)."""
        cnx = db.connect()
        db.run_query(cnx, "DELETE FROM asteroid_tags WHERE tag_id = %s", (tag_id,))
        cnx.close()
        return {"status": True, "msg": "Tag deleted"}


@blp.route("/asteroids/<int:asteroid_id>/tags")
class AsteroidTagAttachResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidTagAttachRequestSchema)
    @blp.response(200, StatusMsgSchema)
    def post(self, data, asteroid_id):
        """Attach an existing tag to an asteroid."""
        tag_id = data["tag_id"]
        cnx = db.connect()
        asteroid = db.run_query(cnx, "SELECT id FROM asteroids WHERE id = %s", (asteroid_id,))
        tag = db.run_query(cnx, "SELECT tag_id FROM asteroid_tags WHERE tag_id = %s", (tag_id,))
        if not asteroid or not tag:
            cnx.close()
            return {"status": False, "msg": "Asteroid or tag not found"}
        db.asteroid_tag_attach(cnx, asteroid_id, tag_id)
        cnx.close()
        return {"status": True, "msg": "Tag added"}


@blp.route("/asteroids/<int:asteroid_id>/tags/<int:tag_id>")
class AsteroidTagDetachResource(MethodView):
    @jwt_required()
    @blp.response(200, StatusMsgSchema)
    def delete(self, asteroid_id, tag_id):
        """Detach a tag from an asteroid."""
        cnx = db.connect()
        db.asteroid_tag_detach(cnx, asteroid_id, tag_id)
        cnx.close()
        return {"status": True, "msg": "Tag removed"}


# Register blueprint
api.register_blueprint(blp)


if __name__ == '__main__':
    app.run()
