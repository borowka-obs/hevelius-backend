"""Register API route modules (import side-effects attach views to blp)."""

import importlib


def register_blueprints(api, app):
    """Import route modules (registers MethodViews on blp) and attach the blueprint."""
    # pylint: disable=import-outside-toplevel
    from hevelius.api.blueprint import blp
    from hevelius.api.routes.misc import register_misc_routes

    # Import for side effects: each module registers MethodViews on blp.
    for _mod in (
        "auth_users",
        "tasks",
        "scopes",
        "filters",
        "sensors",
        "projects",
        "catalogs",
        "asteroids",
    ):
        importlib.import_module(f"hevelius.api.routes.{_mod}")

    register_misc_routes(app)
    api.register_blueprint(blp)
