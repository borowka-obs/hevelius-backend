import logging

from flask.views import MethodView
from flask_jwt_extended import jwt_required


from hevelius import db
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    ScopeCreateResponseSchema,
    ScopeCreateSchema,
    ScopeDetailResponseSchema,
    ScopeFilterIdBodySchema,
    ScopeUpdateSchema,
    ScopesListQuerySchema,
    StatusMsgSchema,
    TelescopesListSchema,
)

logger = logging.getLogger(__name__)


def _scopes_base_query():
    return """
        SELECT t.scope_id, t.name, t.descr, t.min_dec, t.max_dec, t.focal, t.aperture,
               t.lon, t.lat, t.alt, t.sensor_id, t.active, t.default_rotation,
               s.sensor_id, s.name, s.resx, s.resy, s.pixel_x, s.pixel_y,
               s.bits, s.width, s.height, s.vendor, s.url, s.active AS sensor_active
        FROM telescopes t
        LEFT JOIN sensors s ON t.sensor_id = s.sensor_id
    """


def _fetch_filters_for_scopes(cnx, scope_ids):
    if not scope_ids:
        return {}
    placeholders = ",".join(["%s"] * len(scope_ids))
    tf_query = f"""
        SELECT tf.scope_id, f.filter_id, f.short_name, f.full_name, f.url, f.active
        FROM telescope_filters tf
        JOIN filters f ON tf.filter_id = f.filter_id
        WHERE tf.scope_id IN ({placeholders})
        ORDER BY tf.scope_id, f.filter_id
    """
    tf_rows = db.run_query(cnx, tf_query, scope_ids)
    out = {}
    for r in (tf_rows or []):
        sid = r[0]
        if sid not in out:
            out[sid] = []
        out[sid].append({'filter_id': r[1], 'short_name': r[2], 'full_name': r[3], 'url': r[4], 'active': r[5]})
    return out


@blp.route("/scopes")
class ScopesResource(MethodView):
    @jwt_required()
    @blp.arguments(ScopesListQuerySchema, location="query")
    @blp.response(200, TelescopesListSchema)
    def get(self, args):
        """Get list of telescopes with their associated sensors and filters. Supports sorting."""
        sort_by = args.get("sort_by") or "scope_id"
        sort_order = (args.get("sort_order") or "asc").upper()
        if sort_by not in ("scope_id", "name", "focal", "active"):
            sort_by = "scope_id"
        if sort_order not in ("ASC", "DESC"):
            sort_order = "ASC"
        order_col = "t.scope_id" if sort_by == "scope_id" else f"t.{sort_by}"
        query = _scopes_base_query() + f" ORDER BY {order_col} {sort_order}"
        cnx = db.connect()
        results = db.run_query(cnx, query)
        scope_ids = [r[0] for r in (results or [])]
        telescope_filters = _fetch_filters_for_scopes(cnx, scope_ids)
        cnx.close()
        telescopes = [_telescope_row_to_dict(row, telescope_filters.get(row[0], [])) for row in (results or [])]
        return {"telescopes": telescopes}

    @jwt_required()
    @blp.arguments(ScopeCreateSchema)
    @blp.response(200, ScopeCreateResponseSchema)
    def post(self, data):
        """Add new telescope. name required; scope_id optional (auto-assigned if omitted)."""
        name = data["name"]
        scope_id = data.get("scope_id")
        sensor_id = data.get("sensor_id")
        if sensor_id == 0:
            sensor_id = None
        cnx = db.connect()
        if scope_id is None:
            row = db.run_query(cnx, "SELECT COALESCE(MAX(scope_id), 0) + 1 FROM telescopes")
            scope_id = row[0][0] if row else 1
        else:
            existing = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
            if existing:
                cnx.close()
                return {"status": False, "scope_id": None, "scope": None, "msg": f"Telescope scope_id={scope_id} already exists"}
        cols = ["scope_id", "name"]
        vals = [scope_id, name]
        for key in ("descr", "min_dec", "max_dec", "focal", "aperture", "lon", "lat", "alt", "active", "default_rotation"):
            if data.get(key) is not None:
                cols.append(key)
                vals.append(data[key])
        if sensor_id is not None:
            cols.append("sensor_id")
            vals.append(sensor_id)
        placeholders = ", ".join(["%s"] * len(vals))
        try:
            db.run_query(cnx, f"INSERT INTO telescopes ({', '.join(cols)}) VALUES ({placeholders})", vals)
        except Exception as e:
            cnx.close()
            return {"status": False, "scope_id": None, "scope": None, "msg": str(e)}
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, [])) if row else {
            "scope_id": scope_id, "name": name, "descr": data.get("descr"), "min_dec": data.get("min_dec"),
            "max_dec": data.get("max_dec"), "focal": data.get("focal"), "aperture": data.get("aperture"),
            "lon": data.get("lon"), "lat": data.get("lat"), "alt": data.get("alt"), "sensor": None,
            "filters": [], "active": data.get("active", True), "default_rotation": data.get("default_rotation")
        }
        return {"status": True, "scope_id": scope_id, "scope": scope, "msg": "Created"}


@blp.route("/scopes/<int:scope_id>")
class ScopeDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, ScopeDetailResponseSchema)
    def get(self, scope_id):
        """Get telescope details with sensor and filters."""
        cnx = db.connect()
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        if not row:
            cnx.close()
            return {"status": False, "scope": None, "msg": f"Telescope scope_id={scope_id} not found"}
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, []))
        return {"status": True, "scope": scope, "msg": "OK"}

    @jwt_required()
    @blp.arguments(ScopeUpdateSchema)
    @blp.response(200, ScopeDetailResponseSchema)
    def patch(self, data, scope_id):
        """Edit telescope. Use sensor_id 0 to remove sensor."""
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
        if not row:
            cnx.close()
            return {"status": False, "scope": None, "msg": f"Telescope scope_id={scope_id} not found"}
        updates = []
        params = []
        for key in ("name", "descr", "min_dec", "max_dec", "focal", "aperture", "lon", "lat", "alt", "active"):
            if data.get(key) is not None:
                updates.append(f"{key} = %s")
                params.append(data[key])
        if "default_rotation" in data:
            updates.append("default_rotation = %s")
            params.append(data["default_rotation"])   # None is valid — clears the value
        if "sensor_id" in data:
            sid = data["sensor_id"]
            updates.append("sensor_id = %s")
            params.append(None if sid == 0 else sid)
        if updates:
            params.append(scope_id)
            db.run_query(cnx, "UPDATE telescopes SET " + ", ".join(updates) + " WHERE scope_id = %s", tuple(params))
        row = db.run_query(cnx, _scopes_base_query() + " WHERE t.scope_id = %s", (scope_id,))
        filters_list = _fetch_filters_for_scopes(cnx, [scope_id])
        cnx.close()
        scope = _telescope_row_to_dict(row[0], filters_list.get(scope_id, [])) if row else None
        return {"status": True, "scope": scope, "msg": "Updated"}


@blp.route("/scopes/<int:scope_id>/filters")
class ScopeFiltersResource(MethodView):
    @jwt_required()
    @blp.arguments(ScopeFilterIdBodySchema)
    @blp.response(200, StatusMsgSchema)
    def post(self, data, scope_id):
        """Add filter to telescope."""
        filter_id = data["filter_id"]
        cnx = db.connect()
        scope = db.run_query(cnx, "SELECT scope_id FROM telescopes WHERE scope_id = %s", (scope_id,))
        flt = db.run_query(cnx, "SELECT filter_id FROM filters WHERE filter_id = %s", (filter_id,))
        if not scope or not flt:
            cnx.close()
            return {"status": False, "msg": "Telescope or filter not found"}
        try:
            db.run_query(cnx, "INSERT INTO telescope_filters (scope_id, filter_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (scope_id, filter_id))
        except Exception as e:
            cnx.close()
            return {"status": False, "msg": str(e)}
        cnx.close()
        return {"status": True, "msg": "Filter added"}


@blp.route("/scopes/<int:scope_id>/filters/<int:filter_id>")
class ScopeFilterRemoveResource(MethodView):
    @jwt_required()
    @blp.response(200, StatusMsgSchema)
    def delete(self, scope_id, filter_id):
        """Remove filter from telescope."""
        cnx = db.connect()
        db.run_query(cnx, "DELETE FROM telescope_filters WHERE scope_id = %s AND filter_id = %s", (scope_id, filter_id))
        cnx.close()
        return {"status": True, "msg": "Filter removed"}


def _row_to_filter(r):
    return {"filter_id": r[0], "short_name": r[1], "full_name": r[2], "url": r[3], "active": r[4]}


def _telescope_row_to_dict(row, filters_list=None):
    """Build telescope dict from main query row (t + s columns). filters_list is optional."""
    telescope = {
        'scope_id': row[0],
        'name': row[1],
        'descr': row[2],
        'min_dec': row[3],
        'max_dec': row[4],
        'focal': row[5],
        'aperture': row[6],
        'lon': row[7],
        'lat': row[8],
        'alt': row[9],
        'active': row[11],
        'default_rotation': row[12],
        'filters': filters_list or []
    }
    if row[10] is not None:  # sensor_id
        telescope['sensor'] = {
            'sensor_id': row[13], 'name': row[14], 'resx': row[15], 'resy': row[16],
            'pixel_x': row[17], 'pixel_y': row[18], 'bits': row[19],
            'width': row[20], 'height': row[21],
            'vendor': row[22], 'url': row[23], 'active': row[24]
        }
    else:
        telescope['sensor'] = None
    return telescope
