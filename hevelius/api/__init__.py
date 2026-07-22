"""Hevelius REST API (Flask).

Usage:
    python -m hevelius.api
    flask --app hevelius.api:app run
    gunicorn 'hevelius.api:app'
"""
import os
from datetime import timedelta
from pathlib import Path

import yaml
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_smorest import Api

from hevelius import db
from hevelius.api.auth_utils import normalize_jwt_secret, jwt_identity_to_string


def create_app():
    """Application factory for the Hevelius REST API."""
    pkg_dir = Path(__file__).resolve().parent
    project_root = pkg_dir.parent.parent

    flask_app = Flask(__name__, template_folder=str(pkg_dir / "templates"))
    CORS(flask_app, support_credentials=True)

    with open(project_root / "api" / "openapi.yaml", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    flask_app.config["API_TITLE"] = spec["info"]["title"]
    flask_app.config["API_VERSION"] = spec["info"]["version"]
    flask_app.config["OPENAPI_VERSION"] = spec["openapi"]
    flask_app.config["OPENAPI_URL_PREFIX"] = "/"
    flask_app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
    flask_app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    flask_app.config["API_SPEC_OPTIONS"] = {"spec": spec}

    config = db.config
    if config.get("jwt") and config.get("jwt").get("secret-key"):
        jwt_secret = config.get("jwt").get("secret-key")
    else:
        jwt_secret = os.getenv("JWT_SECRET_KEY")

    if not jwt_secret:
        raise RuntimeError("JWT_SECRET_KEY not found in config or environment variables")

    flask_app.config["JWT_SECRET_KEY"] = normalize_jwt_secret(jwt_secret)
    flask_app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

    jwt = JWTManager(flask_app)
    jwt.user_identity_loader(jwt_identity_to_string)

    api = Api(flask_app)
    # Deferred to avoid circular imports while route modules register on blp.
    from hevelius.api.routes import register_blueprints  # pylint: disable=import-outside-toplevel
    register_blueprints(api, flask_app)

    return flask_app


app = create_app()
