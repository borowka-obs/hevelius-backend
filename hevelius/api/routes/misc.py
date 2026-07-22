"""Non-/api Flask routes."""
import json
import plotly
from flask import render_template

from hevelius import stats


def register_misc_routes(app):
    """Register non-/api routes (homepage stub and histogram HTML page)."""
    @app.route("/")
    def root():
        """Just a stub API homepage."""
        return "Nothing to see here. Move along."

    @app.route("/histo")
    def histogram():
        """Generates 2D diagram of observation density. Returns a HTML page with
        embedded plotly image."""
        fig = stats.histogram_figure_get({})
        graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        return render_template("histogram.html", graphJSON=graph_json)
