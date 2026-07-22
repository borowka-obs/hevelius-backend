"""Shared flask-smorest blueprint for /api routes."""
from flask_smorest import Blueprint

blp = Blueprint("api", __name__, url_prefix="/api")
