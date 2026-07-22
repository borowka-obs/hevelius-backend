"""Register API route modules (import side-effects attach views to blp)."""


def register_blueprints(api, app):
    """Import route modules (registers MethodViews on blp) and attach the blueprint."""
    # pylint: disable=import-outside-toplevel,unused-import
    from hevelius.api.blueprint import blp
    from hevelius.api.routes import (
        auth_users,
        tasks,
        scopes,
        filters,
        sensors,
        projects,
        catalogs,
        asteroids,
    )
    from hevelius.api.routes.misc import register_misc_routes

    register_misc_routes(app)
    api.register_blueprint(blp)
