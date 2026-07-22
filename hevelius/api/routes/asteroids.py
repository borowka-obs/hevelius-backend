"""Asteroid and asteroid-tag API routes."""

import logging
from datetime import date

from flask.views import MethodView
from flask_jwt_extended import jwt_required
from flask_smorest import abort

from astropy.coordinates import EarthLocation
from astropy import units as u

from hevelius import asteroid, db
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    AsteroidDetailResponseSchema,
    AsteroidTagAttachRequestSchema,
    AsteroidTagCreateResponseSchema,
    AsteroidTagCreateSchema,
    AsteroidTagDetailResponseSchema,
    AsteroidTagUpdateSchema,
    AsteroidTagsListResponseSchema,
    AsteroidVisibilityQuerySchema,
    AsteroidVisibilityResponseSchema,
    AsteroidsListRequestSchema,
    AsteroidsListResponseSchema,
    StatusMsgSchema,
)

logger = logging.getLogger(__name__)


def _asteroid_row_to_dict(row, tags=None):
    (asteroid_id, number, designation, name, epoch, mean_anomaly, perihelion_arg,
     ascending_node, inclination, eccentricity, mean_motion, semimajor_axis,
     absolute_magnitude, slope_parameter) = row
    return {
        'asteroid_id': asteroid_id,
        'number': number,
        'designation': designation,
        'name': name,
        'epoch': epoch,
        'mean_anomaly': mean_anomaly,
        'perihelion_arg': perihelion_arg,
        'ascending_node': ascending_node,
        'inclination': inclination,
        'eccentricity': eccentricity,
        'mean_motion': mean_motion,
        'semimajor_axis': semimajor_axis,
        'absolute_magnitude': absolute_magnitude,
        'slope_parameter': slope_parameter,
        'tags': tags or [],
    }


def _parse_tag_names(raw: str):
    if not raw:
        return None
    names = [n.strip() for n in raw.split(',') if n.strip()]
    return names or None


def _row_to_asteroid_tag(row):
    tag_id, name, description, color, asteroid_count = row
    return {
        'tag_id': tag_id, 'name': name, 'description': description,
        'color': color, 'asteroid_count': asteroid_count,
    }


@blp.route("/asteroids")
class AsteroidsListResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidsListRequestSchema, location="query")
    @blp.response(200, AsteroidsListResponseSchema)
    def get(self, args):
        """Get list of asteroids with paging, sorting, and filtering"""
        return self._get_asteroids(args)

    @jwt_required()
    @blp.arguments(AsteroidsListRequestSchema)
    @blp.response(200, AsteroidsListResponseSchema)
    def post(self, args):
        """Get list of asteroids with paging, sorting, and filtering"""
        return self._get_asteroids(args)

    def _get_asteroids(self, args):
        """Helper method to get asteroids based on filters, sorting, and paging"""
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page
        tag_names = _parse_tag_names(args.get('tags'))
        tags_mode = args.get('tags_mode', 'any')

        cnx = db.connect()
        total_count = db.asteroids_count(
            cnx,
            designation=args.get('designation'),
            name=args.get('name'),
            number=args.get('number'),
            numbered=args.get('numbered'),
            mag_min=args.get('mag_min'),
            mag_max=args.get('mag_max'),
            tag_names=tag_names,
            tags_mode=tags_mode,
        )
        asteroids_list = db.asteroids_search(
            cnx,
            designation=args.get('designation'),
            name=args.get('name'),
            number=args.get('number'),
            numbered=args.get('numbered'),
            mag_min=args.get('mag_min'),
            mag_max=args.get('mag_max'),
            tag_names=tag_names,
            tags_mode=tags_mode,
            sort_by=args.get('sort_by', 'number'),
            sort_order=args.get('sort_order', 'asc'),
            limit=per_page,
            offset=offset,
        )
        tags_by_asteroid = db.asteroid_tags_for_asteroids(cnx, [row[0] for row in asteroids_list])
        cnx.close()

        logger.info(
            "Asteroid list: returned %d entries (page %d, total matching: %d)",
            len(asteroids_list), page, total_count
        )

        total_pages = (total_count + per_page - 1) // per_page if per_page else 0

        return {
            "asteroids": [
                _asteroid_row_to_dict(row, tags=tags_by_asteroid.get(row[0]))
                for row in asteroids_list
            ],
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages,
        }


@blp.route("/asteroids/<int:asteroid_id>")
class AsteroidDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, AsteroidDetailResponseSchema)
    def get(self, asteroid_id):
        """Get single asteroid by ID"""
        cnx = db.connect()
        row = db.asteroid_get_by_id(cnx, asteroid_id)
        if row is None:
            cnx.close()
            abort(404, message="Asteroid not found.")
        tags = db.asteroid_tags_for_asteroids(cnx, [asteroid_id]).get(asteroid_id)
        cnx.close()
        return {"status": True, "asteroid": _asteroid_row_to_dict(row, tags=tags), "msg": "OK"}


@blp.route("/asteroids/<int:asteroid_id>/visibility")
class AsteroidVisibilityResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidVisibilityQuerySchema, location="query")
    @blp.response(200, AsteroidVisibilityResponseSchema)
    def get(self, args, asteroid_id):
        """
        Compute altitude/azimuth/magnitude across a night for one asteroid as
        seen from a telescope's location. Defaults to tonight; pass `date` to
        check a different night. The orbital mechanics live in
        hevelius.asteroid so the same computation can be reused by a
        future CLI command.
        """
        cnx = db.connect()
        asteroid_row = db.asteroid_get_by_id(cnx, asteroid_id)
        if asteroid_row is None:
            cnx.close()
            abort(404, message="Asteroid not found.")

        scope_id = args["scope_id"]
        scope_rows = db.run_query(
            cnx, "SELECT name, lat, lon, alt FROM telescopes WHERE scope_id = %s", (scope_id,)
        )
        cnx.close()
        if not scope_rows:
            abort(404, message="Telescope not found.")
        scope_name, lat, lon, alt = scope_rows[0]
        if lat is None or lon is None:
            abort(400, message="Telescope has no location (lat/lon) configured.")

        obs_date = args.get("date") or date.today()
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=(alt or 0) * u.m)  # pylint: disable=no-member

        result = asteroid.compute_asteroid_visibility_curve(
            asteroid_row[1:], location, obs_date.isoformat(), step_minutes=args.get("step_minutes", 10),
        )

        return {
            "status": True,
            "scope_id": scope_id,
            "scope_name": scope_name,
            **result,
            "msg": "OK",
        }


@blp.route("/asteroid-tags")
class AsteroidTagsResource(MethodView):
    @jwt_required()
    @blp.response(200, AsteroidTagsListResponseSchema)
    def get(self):
        """List all asteroid tags, with the number of asteroids carrying each."""
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT t.tag_id, t.name, t.description, t.color, COUNT(m.asteroid_id)
               FROM asteroid_tags t
               LEFT JOIN asteroid_tag_map m ON m.tag_id = t.tag_id
               GROUP BY t.tag_id
               ORDER BY t.name""",
        )
        cnx.close()
        return {"tags": [_row_to_asteroid_tag(r) for r in (rows or [])]}

    @jwt_required()
    @blp.arguments(AsteroidTagCreateSchema)
    @blp.response(200, AsteroidTagCreateResponseSchema)
    def post(self, tag_data):
        """Create a new asteroid tag (e.g. amor, neo, pha, fast rotator)."""
        cnx = db.connect()
        try:
            row = db.run_query(
                cnx,
                "INSERT INTO asteroid_tags (name, description, color) VALUES (%s, %s, %s) RETURNING tag_id",
                (tag_data["name"], tag_data.get("description"), tag_data.get("color")),
            )
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Tag with this name already exists.")
            raise
        tag_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if tag_id is None:
            abort(500, message="Failed to create tag.")
        return {
            "status": True,
            "tag_id": tag_id,
            "tag": {
                "tag_id": tag_id, "name": tag_data["name"],
                "description": tag_data.get("description"), "color": tag_data.get("color"),
                "asteroid_count": 0,
            },
            "msg": "Tag created successfully.",
        }


@blp.route("/asteroid-tags/<int:tag_id>")
class AsteroidTagDetailResource(MethodView):
    def _fetch(self, cnx, tag_id):
        rows = db.run_query(
            cnx,
            """SELECT t.tag_id, t.name, t.description, t.color, COUNT(m.asteroid_id)
               FROM asteroid_tags t
               LEFT JOIN asteroid_tag_map m ON m.tag_id = t.tag_id
               WHERE t.tag_id = %s
               GROUP BY t.tag_id""",
            (tag_id,),
        )
        return rows[0] if rows else None

    @jwt_required()
    @blp.response(200, AsteroidTagDetailResponseSchema)
    def get(self, tag_id):
        """Get a single asteroid tag."""
        cnx = db.connect()
        row = self._fetch(cnx, tag_id)
        cnx.close()
        if row is None:
            abort(404, message="Tag not found.")
        return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "OK"}

    @jwt_required()
    @blp.arguments(AsteroidTagUpdateSchema)
    @blp.response(200, AsteroidTagDetailResponseSchema)
    def patch(self, tag_data, tag_id):
        """Edit an asteroid tag (partial update: name, description, color)."""
        cnx = db.connect()
        if self._fetch(cnx, tag_id) is None:
            cnx.close()
            abort(404, message="Tag not found.")
        updates = []
        params = []
        for key in ("name", "description", "color"):
            if key in tag_data:
                updates.append(f"{key} = %s")
                params.append(tag_data[key])
        if not updates:
            row = self._fetch(cnx, tag_id)
            cnx.close()
            return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "No changes."}
        params.append(tag_id)
        try:
            db.run_query(cnx, "UPDATE asteroid_tags SET " + ", ".join(updates) + " WHERE tag_id = %s", tuple(params))
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Tag with this name already exists.")
            raise
        row = self._fetch(cnx, tag_id)
        cnx.close()
        return {"status": True, "tag": _row_to_asteroid_tag(row), "msg": "Tag updated."}

    @jwt_required()
    @blp.response(200, StatusMsgSchema)
    def delete(self, tag_id):
        """Delete an asteroid tag (also removes it from any tagged asteroids)."""
        cnx = db.connect()
        if self._fetch(cnx, tag_id) is None:
            cnx.close()
            abort(404, message="Tag not found.")
        db.run_query(cnx, "DELETE FROM asteroid_tags WHERE tag_id = %s", (tag_id,))
        cnx.close()
        return {"status": True, "msg": "Tag deleted"}


@blp.route("/asteroids/<int:asteroid_id>/tags")
class AsteroidTagAttachResource(MethodView):
    @jwt_required()
    @blp.arguments(AsteroidTagAttachRequestSchema)
    @blp.response(200, StatusMsgSchema)
    def post(self, data, asteroid_id):
        """Attach an existing tag to an asteroid."""
        tag_id = data["tag_id"]
        cnx = db.connect()
        asteroid_rows = db.run_query(cnx, "SELECT id FROM asteroids WHERE id = %s", (asteroid_id,))
        tag = db.run_query(cnx, "SELECT tag_id FROM asteroid_tags WHERE tag_id = %s", (tag_id,))
        if not asteroid_rows or not tag:
            cnx.close()
            abort(404, message="Asteroid or tag not found.")
        db.asteroid_tag_attach(cnx, asteroid_id, tag_id)
        cnx.close()
        return {"status": True, "msg": "Tag added"}


@blp.route("/asteroids/<int:asteroid_id>/tags/<int:tag_id>")
class AsteroidTagDetachResource(MethodView):
    @jwt_required()
    @blp.response(200, StatusMsgSchema)
    def delete(self, asteroid_id, tag_id):
        """Detach a tag from an asteroid."""
        cnx = db.connect()
        db.asteroid_tag_detach(cnx, asteroid_id, tag_id)
        cnx.close()
        return {"status": True, "msg": "Tag removed"}
