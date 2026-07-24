"""Non-/api Flask routes."""


def register_misc_routes(app):
    """Register non-/api routes (homepage stub)."""
    @app.route("/")
    def root():
        """Just a stub API homepage."""
        return "Nothing to see here. Move along."
