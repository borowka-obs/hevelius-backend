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

    app = Flask(__name__, template_folder=str(pkg_dir / "templates"))
    CORS(app, support_credentials=True)

    with open(project_root / "api" / "openapi.yaml") as f:
        spec = yaml.safe_load(f)

    app.config["API_TITLE"] = spec["info"]["title"]
    app.config["API_VERSION"] = spec["info"]["version"]
    app.config["OPENAPI_VERSION"] = spec["openapi"]
    app.config["OPENAPI_URL_PREFIX"] = "/"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
    app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    app.config["API_SPEC_OPTIONS"] = {"spec": spec}

    config = db.config
    if config.get("jwt") and config.get("jwt").get("secret-key"):
        jwt_secret = config.get("jwt").get("secret-key")
    else:
        jwt_secret = os.getenv("JWT_SECRET_KEY")

    if not jwt_secret:
        raise RuntimeError("JWT_SECRET_KEY not found in config or environment variables")

    app.config["JWT_SECRET_KEY"] = normalize_jwt_secret(jwt_secret)
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

    jwt = JWTManager(app)
    jwt.user_identity_loader(jwt_identity_to_string)

    api = Api(app)
    from hevelius.api.routes import register_blueprints
    register_blueprints(api, app)

    return app


app = create_app()
