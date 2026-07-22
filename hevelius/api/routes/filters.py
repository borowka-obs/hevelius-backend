from hevelius.api.routes.scopes import _row_to_filter
import logging

from flask import request
from flask.views import MethodView
from flask_jwt_extended import jwt_required
from flask_smorest import abort


from hevelius import db
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    FilterCreateResponseSchema,
    FilterCreateSchema,
    FilterDetailResponseSchema,
    FilterUpdateSchema,
    FiltersListResponseSchema,
)

logger = logging.getLogger(__name__)


@blp.route("/filters")
class FiltersResource(MethodView):
    @jwt_required()
    @blp.response(200, FiltersListResponseSchema)
    def get(self):
        """Get list of filters. Sortable by filter_id, short_name, full_name, active (default filter_id)."""
        active = request.args.get("active", type=lambda v: v.lower() == "true" if isinstance(v, str) else None)
        sort_by = request.args.get("sort_by", "filter_id")
        sort_order = (request.args.get("sort_order") or "asc").upper()
        if sort_by not in ("filter_id", "short_name", "full_name", "active"):
            sort_by = "filter_id"
        if sort_order not in ("ASC", "DESC"):
            sort_order = "ASC"
        query = "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE 1=1"
        params = []
        if active is not None:
            query += " AND active = %s"
            params.append(active)
        query += f" ORDER BY {sort_by} {sort_order}"
        cnx = db.connect()
        rows = db.run_query(cnx, query, params if params else None)
        cnx.close()
        filters_list = [_row_to_filter(r) for r in (rows or [])]
        return {"filters": filters_list}

    @jwt_required()
    @blp.arguments(FilterCreateSchema)
    @blp.response(200, FilterCreateResponseSchema)
    def post(self, filter_data):
        """Add new filter"""
        short_name = filter_data["short_name"]
        full_name = filter_data.get("full_name")
        url = filter_data.get("url")
        active = filter_data.get("active", True)
        cnx = db.connect()
        try:
            row = db.run_query(
                cnx,
                "INSERT INTO filters (short_name, full_name, url, active) VALUES (%s, %s, %s, %s) RETURNING filter_id",
                (short_name, full_name, url, active)
            )
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Filter with this short_name already exists.")
            raise
        filter_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if filter_id is None:
            abort(500, message="Failed to create filter.")
        # Fetch the created row
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        if not rows:
            abort(500, message="Filter created but could not be retrieved.")
        return {
            "status": True,
            "filter_id": filter_id,
            "filter": _row_to_filter(rows[0]),
            "msg": "Filter created successfully."
        }


@blp.route("/filters/<int:filter_id>")
class FilterDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, FilterDetailResponseSchema)
    def get(self, filter_id):
        """Get single filter"""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        if not rows:
            abort(404, message="Filter not found.")
        return {"status": True, "filter": _row_to_filter(rows[0]), "msg": "OK"}

    @jwt_required()
    @blp.arguments(FilterUpdateSchema)
    @blp.response(200, FilterDetailResponseSchema)
    def patch(self, filter_data, filter_id):
        """Edit filter (partial update). Set active true/false to activate or deactivate."""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        if not rows:
            cnx.close()
            abort(404, message="Filter not found.")
        updates = []
        params = []
        for key in ("short_name", "full_name", "url", "active"):
            if key in filter_data and filter_data[key] is not None:
                updates.append(f"{key} = %s")
                params.append(filter_data[key])
        if not updates:
            cnx.close()
            return {"status": True, "filter": _row_to_filter(rows[0]), "msg": "No changes."}
        params.append(filter_id)
        try:
            db.run_query(cnx, "UPDATE filters SET " + ", ".join(updates) + " WHERE filter_id = %s", tuple(params))
        except Exception as e:
            cnx.close()
            err = str(e).lower()
            if "unique constraint" in err or "duplicate key" in err:
                abort(400, message="Filter with this short_name already exists.")
            raise
        updated = db.run_query(cnx, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE filter_id = %s", (filter_id,))
        cnx.close()
        return {"status": True, "filter": _row_to_filter(updated[0]), "msg": "Filter updated."}
