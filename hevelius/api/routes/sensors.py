"""Camera sensor inventory API routes."""

import logging

from flask import request
from flask.views import MethodView
from flask_jwt_extended import jwt_required
from flask_smorest import abort


from hevelius import db
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    SensorCreateResponseSchema,
    SensorCreateSchema,
    SensorDetailResponseSchema,
    SensorUpdateSchema,
    SensorsListResponseSchema,
)

logger = logging.getLogger(__name__)

SENSOR_SORT_FIELDS = {"sensor_id", "name", "resx", "resy", "pixel_x", "pixel_y", "width", "height", "vendor"}


def _round2(val):
    """Round to 2 decimal places for display; None stays None."""
    return round(val, 2) if val is not None else None


def _row_to_sensor(r):
    return {
        "sensor_id": r[0], "name": r[1], "resx": r[2], "resy": r[3],
        "pixel_x": r[4], "pixel_y": r[5], "bits": r[6],
        "width": _round2(r[7]), "height": _round2(r[8]),
        "vendor": r[9], "url": r[10], "active": r[11]
    }


@blp.route("/sensors")
class SensorsResource(MethodView):
    @jwt_required()
    @blp.response(200, SensorsListResponseSchema)
    def get(self):
        """Get list of sensors (cameras) with optional sorting"""
        active = request.args.get("active", type=lambda v: v.lower() == "true" if isinstance(v, str) else None)
        sort_by = request.args.get("sort_by", "sensor_id")
        sort_order = request.args.get("sort_order", "asc")
        if sort_by not in SENSOR_SORT_FIELDS:
            sort_by = "sensor_id"
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"
        query = """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active
                   FROM sensors WHERE 1=1"""
        params = []
        if active is not None:
            query += " AND active = %s"
            params.append(active)
        query += f" ORDER BY {sort_by} {sort_order}"
        cnx = db.connect()
        rows = db.run_query(cnx, query, params if params else None)
        cnx.close()
        sensors_list = [_row_to_sensor(r) for r in (rows or [])]
        return {"sensors": sensors_list}

    @jwt_required()
    @blp.arguments(SensorCreateSchema)
    @blp.response(200, SensorCreateResponseSchema)
    def post(self, sensor_data):
        """Add new sensor. width/height computed from resx*px/1000 if not provided. bits defaults to 0."""
        name = sensor_data["name"]
        resx = sensor_data["resx"]
        resy = sensor_data["resy"]
        pixel_x = sensor_data["pixel_x"]
        pixel_y = sensor_data["pixel_y"]
        bits = sensor_data.get("bits") if sensor_data.get("bits") is not None else 0
        width = sensor_data.get("width")
        height = sensor_data.get("height")
        if width is None:
            width = round(resx * pixel_x / 1000.0, 2)
        else:
            width = round(width, 2)
        if height is None:
            height = round(resy * pixel_y / 1000.0, 2)
        else:
            height = round(height, 2)
        cnx = db.connect()
        row = db.run_query(
            cnx,
            """INSERT INTO sensors (name, resx, resy, pixel_x, pixel_y, bits, width, height, vendor, url, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING sensor_id""",
            (
                name,
                resx,
                resy,
                pixel_x,
                pixel_y,
                bits,
                width,
                height,
                sensor_data.get("vendor"),
                sensor_data.get("url"),
                sensor_data.get("active", True),
            )
        )
        sensor_id = row if isinstance(row, int) else (row[0] if row else None)
        cnx.close()
        if sensor_id is None:
            abort(500, message="Failed to create sensor.")
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                        vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        if not rows:
            abort(500, message="Sensor created but could not be retrieved.")
        return {
            "status": True,
            "sensor_id": sensor_id,
            "sensor": _row_to_sensor(rows[0]),
            "msg": "Sensor created successfully."
        }


@blp.route("/sensors/<int:sensor_id>")
class SensorDetailResource(MethodView):
    @jwt_required()
    @blp.response(200, SensorDetailResponseSchema)
    def get(self, sensor_id):
        """Get single sensor"""
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                       vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        if not rows:
            abort(404, message="Sensor not found.")
        return {"status": True, "sensor": _row_to_sensor(rows[0]), "msg": "OK"}

    @jwt_required()
    @blp.arguments(SensorUpdateSchema)
    @blp.response(200, SensorDetailResponseSchema)
    def patch(self, sensor_data, sensor_id):
        """Edit sensor (partial update)"""
        cnx = db.connect()
        rows = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                       vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        if not rows:
            cnx.close()
            abort(404, message="Sensor not found.")
        updates = []
        params = []
        for key in ("name", "resx", "resy", "pixel_x", "pixel_y", "bits", "width", "height", "vendor", "url", "active"):
            if key in sensor_data and sensor_data[key] is not None:
                updates.append(f"{key} = %s")
                params.append(sensor_data[key])
        if not updates:
            cnx.close()
            return {"status": True, "sensor": _row_to_sensor(rows[0]), "msg": "No changes."}
        params.append(sensor_id)
        db.run_query(cnx, "UPDATE sensors SET " + ", ".join(updates) + " WHERE sensor_id = %s", tuple(params))
        updated = db.run_query(cnx, """SELECT sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height,
                                         vendor, url, active FROM sensors WHERE sensor_id = %s""", (sensor_id,))
        cnx.close()
        return {"status": True, "sensor": _row_to_sensor(updated[0]), "msg": "Sensor updated."}
