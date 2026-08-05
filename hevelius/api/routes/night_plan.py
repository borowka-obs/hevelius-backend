"""Night plan API routes (OS-4, #46)."""

import logging

from flask.views import MethodView
from flask_jwt_extended import jwt_required
from flask_smorest import abort

from hevelius import db, night_plan
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    NightPlanRequestSchema,
    NightPlanResponseSchema,
)

logger = logging.getLogger(__name__)


@blp.route("/night-plan")
class NightPlanResource(MethodView):
    @jwt_required()
    @blp.arguments(NightPlanRequestSchema, location="query")
    @blp.response(200, NightPlanResponseSchema)
    def get(self, args):
        """Get the observing plan for one telescope and one night
        Returns the tasks and projects that are actually observable during the
        night, each with the altitude/azimuth and sun/moon geometry it was
        accepted on, plus the night's own sunset/sunrise and moon times. Pass
        explain=true to also get everything that was left out, and why.
        """
        return self._night_plan(args)

    @jwt_required()
    @blp.arguments(NightPlanRequestSchema)
    @blp.response(200, NightPlanResponseSchema)
    def post(self, args):
        """Get the observing plan for one telescope and one night
        Body-parameter variant of the GET above, with identical semantics.
        """
        return self._night_plan(args)

    def _night_plan(self, args):
        cnx = db.connect()
        try:
            return night_plan.compute_night_plan(
                cnx,
                scope_id=args["scope_id"],
                night_date=args.get("date"),
                user_id=args.get("user_id"),
                explain=args.get("explain", False),
            )
        except night_plan.NightPlanError as err:
            logger.info("night-plan rejected: %s", err.message)
            abort(err.status, message=err.message)
        finally:
            cnx.close()
