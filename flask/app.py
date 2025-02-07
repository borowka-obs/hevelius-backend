"""
Flask application that provides a REST API to the Hevelius backend.
"""

from flask import Flask, render_template, request
from flask_cors import CORS
from flask_smorest import Api, Blueprint
import yaml
import json
import plotly
from marshmallow import Schema, fields, ValidationError, validate
from flask.views import MethodView
from datetime import datetime  # Add this import at the top

from hevelius import cmd_stats, db

# By default, Flask searches for templates in the templates/ dir.
# Other params: debug=True, port=8080

# Initialize Flask app
app = Flask(__name__)
CORS(app, support_credentials=True)

# Load OpenAPI spec from YAML
with open('openapi.yaml') as f:
    spec = yaml.safe_load(f)

# Configure API documentation
app.config["API_TITLE"] = spec["info"]["title"]
app.config["API_VERSION"] = spec["info"]["version"]
app.config["OPENAPI_VERSION"] = spec["openapi"]
app.config["OPENAPI_URL_PREFIX"] = "/"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
app.config["API_SPEC_OPTIONS"] = {"spec": spec}

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
        validate= validate.Range(min=-90.0, max=90.0, error="Declination must be between -90 and 90"),
        metadata={"description": "Declination (-90 to 90)"}
    )
    exposure = fields.Float(
        metadata={"description": "Exposure time"}
    )
    descr = fields.String(
        validate= validate.Length(max=1024, error="Description must be 1024 characters or less"),
        metadata={"description": "Description"}
    )
    filter = fields.String(
        validate= validate.Length(max=16, error="Filter must be 16 characters or less"),
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
        missing=datetime(2000, 1, 1),
        metadata={"description": "Skip before date"}
    )
    skip_after = fields.DateTime(
        missing=datetime(3000, 1, 1),
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

@app.route('/')
def root():
    """Just a stub API homepage."""
    return "Home🏠 EE"


@app.route('/histo')
def histogram():
    """Generates 2D diagram of observation density. Returns a HTML page with
    embedded plotly image."""

    # example data input
    # df = pd.DataFrame({
    #     'Fruit': ['Apples', 'Oranges', 'Bananas', 'Apples', 'Oranges',
    #               'Bananas'],
    #     'Amount': [4, 1, 2, 2, 4, 5],
    #     'City': ['SF', 'SF', 'SF', 'Montreal', 'Montreal', 'Montreal']
    # })
    # fig = px.bar(df, x='Fruit', y='Amount', color='City', barmode='group')

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

        Returns user information if credentials are valid
        """
        user = login_data.get('username')
        md5pass = login_data.get('password')

        if user is None:
            return {'status': False, 'msg': 'Username not provided'}
        if md5pass is None:
            return {'status': False, 'msg': 'Password not provided'}

        query = f"""SELECT user_id, pass_d, login, firstname, lastname, share, phone, email, permissions,
                aavso_id, ftp_login, ftp_pass FROM users WHERE login='{user}'"""

        cnx = db.connect()
        db_resp = db.run_query(cnx, query)
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

        print(f"User {user} logged in successfully.")
        return {'status': True,
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
                'msg': 'Welcome'}

@blp.route("/task-add")
class TaskAddResource(MethodView):
    @blp.arguments(TaskAddRequestSchema)
    @blp.response(200, TaskAddResponseSchema)
    def post(self, task_data):
        """Add new astronomical observation task"""
        # Prepare fields for SQL query
        fields = []
        values = []
        for key, value in task_data.items():
            if value is not None:
                fields.append(key)
                values.append(value)

        # Create SQL query
        # Create SQL query
        fields_str = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(values))  # Use SQL placeholders
        query = f"""INSERT INTO tasks ({fields_str}, state)
                   VALUES ({placeholders}, 0) RETURNING task_id"""

        print(f"#### Query: {query}")

        try:
            cnx = db.connect()
            result = db.run_query(cnx, query, values)
            print(f"#### Result: {result}")
            cnx.close()

            if result and isinstance(result, int):
                return {
                    'status': True,
                    'task_id': result,
                    'msg': 'Task created successfully'
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

# Register blueprint
api.register_blueprint(blp)
