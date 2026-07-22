"""Marshmallow request/response schemas for the Hevelius REST API."""
from datetime import datetime

from marshmallow import Schema, fields, ValidationError, validate, validates_schema


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
    asteroid_count = fields.Integer(
        metadata={
            "description": (
                "Number of asteroids carrying this tag. Present on tag vocabulary "
                "endpoints; omitted when tags are embedded on asteroid list/detail."
            )
        }
    )


class AsteroidTagCreateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=64),
                         metadata={"description": "Tag name (e.g. amor, neo, pha)"})
    description = fields.String(validate=validate.Length(max=256), load_default=None, allow_none=True)
    color = fields.String(validate=validate.Length(max=16), load_default=None, allow_none=True)


class AsteroidTagUpdateSchema(Schema):
    # No load_default: absent keys stay absent so PATCH can distinguish
    # "leave unchanged" from an explicit null clear of nullable fields.
    name = fields.String(validate=validate.Length(min=1, max=64))
    description = fields.String(validate=validate.Length(max=256), allow_none=True)
    color = fields.String(validate=validate.Length(max=16), allow_none=True)


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
    name = fields.String(allow_none=True, metadata={"description": "Proper name (null if unnamed)"})
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
        ['number', 'designation', 'name', 'absolute_magnitude', 'semimajor_axis',
         'eccentricity', 'inclination', 'mean_motion', 'epoch'],
        error="Invalid sort field. Must be one of: number, designation, name, absolute_magnitude, "
              "semimajor_axis, eccentricity, inclination, mean_motion, epoch"
    ))
    sort_order = fields.String(missing='asc', validate=validate.OneOf(['asc', 'desc']),
                               metadata={"description": "Sort order (asc or desc)"})

    # Filtering parameters
    designation = fields.String(metadata={"description": "Filter by designation (partial match)"})
    name = fields.String(metadata={"description": "Filter by proper name (partial match, case-insensitive)"})
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
        metadata={
            "description": (
                "Evening date (YYYY-MM-DD) whose night to compute; defaults to the "
                "server's local calendar date (not the telescope site's timezone)"
            )
        },
    )
    step_minutes = fields.Integer(
        load_default=10, validate=validate.Range(min=1, max=120),
        metadata={
            "description": (
                "Sampling interval across the night, in minutes "
                "(smaller steps are more CPU-heavy)"
            )
        },
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
    visible = fields.Boolean(metadata={
        "description": (
            "True if max altitude during the night is above the geometric horizon "
            "(altitude > 0°); no airmass or site horizon mask is applied"
        )
    })
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
