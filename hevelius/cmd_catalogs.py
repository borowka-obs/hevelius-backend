"""
CLI commands for listing installed catalogs and searching catalog objects.
"""

import sys
from typing import Any, Dict, List, Optional

from hevelius import db
from hevelius.utils import format_dec, format_ra, parse_dec, parse_ra

CATALOGS_SORT_CHOICES = ("entries", "name")
OBJECT_SORT_CHOICES = ("catalog", "name", "ra", "decl", "const", "type", "magn")


def _catalog_row_to_dict(row) -> Dict[str, Any]:
    return {
        "name": row[0],
        "shortname": row[1],
        "object_count": row[2],
    }


def _object_row_to_dict(row) -> Dict[str, Any]:
    return {
        "object_id": row[0],
        "name": row[1],
        "ra": row[2],
        "decl": row[3],
        "descr": row[4],
        "comment": row[5],
        "type": row[6],
        "epoch": row[7],
        "const": row[8],
        "magn": row[9],
        "x": row[10],
        "y": row[11],
        "altname": row[12],
        "distance": row[13],
        "catalog": row[14],
    }


def fetch_installed_catalogs(sort_by: str = "entries", sort_order: str = "desc") -> List[Dict[str, Any]]:
    """Return installed catalogs as a list of dicts."""
    cnx = db.connect()
    rows = db.catalogs_installed_list(cnx, sort_by=sort_by, sort_order=sort_order)
    cnx.close()
    return [_catalog_row_to_dict(row) for row in rows]


def fetch_catalog_objects(
    catalog: Optional[str] = None,
    constellation: Optional[str] = None,
    name: Optional[str] = None,
    ra_hours: Optional[float] = None,
    decl: Optional[float] = None,
    proximity: float = 1.0,
    sort_by: str = "name",
    sort_order: str = "asc",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return matching catalog objects as a list of dicts."""
    cnx = db.connect()
    rows = db.catalog_objects_search(
        cnx,
        catalog=catalog,
        constellation=constellation,
        name=name,
        ra_hours=ra_hours,
        decl=decl,
        proximity=proximity,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )
    cnx.close()
    return [_object_row_to_dict(row) for row in rows]


def render_catalogs_text(catalogs: List[Dict[str, Any]]) -> str:
    """Format catalog list as plain text."""
    if not catalogs:
        return "No catalogs found."

    lines = [
        f"{'Short':<8} {'Objects':>8}  Name",
        "-" * 72,
    ]
    for entry in catalogs:
        lines.append(
            f"{entry['shortname']:<8} {entry['object_count']:>8}  {entry['name']}"
        )
    return "\n".join(lines)


def render_objects_text(objects: List[Dict[str, Any]]) -> str:
    """Format catalog object search results as plain text."""
    if not objects:
        return "No objects found."

    lines = [
        f"{'Name':<12} {'Catalog':<6} {'Type':<4} {'Const':<4} {'Mag':>6}  "
        f"{'RA':<12} {'Dec':<12}  Description",
        "-" * 96,
    ]
    for obj in objects:
        magn = "" if obj["magn"] is None else f"{obj['magn']:6.1f}"
        ra_str = format_ra(obj["ra"]) if obj["ra"] is not None else ""
        dec_str = format_dec(obj["decl"]) if obj["decl"] is not None else ""
        descr = (obj["descr"] or "")[:40]
        altname = obj["altname"]
        name = obj["name"]
        if altname:
            name = f"{name}/{altname}"
        lines.append(
            f"{name[:12]:<12} {obj['catalog']:<6} {(obj['type'] or ''):<4} "
            f"{(obj['const'] or ''):<4} {magn:>6}  {ra_str:<12} {dec_str:<12}  {descr}"
        )
    return "\n".join(lines)


def _validate_ra_dec_pair(ra_value, dec_value) -> Optional[tuple]:
    """Return (ra_hours, decl) or print an error and exit."""
    has_ra = ra_value is not None
    has_dec = dec_value is not None
    if has_ra != has_dec:
        print("Error: specify both --ra and --dec, or neither.", file=sys.stderr)
        sys.exit(1)
    if not has_ra:
        return None
    try:
        return parse_ra(ra_value), parse_dec(dec_value)
    except (ValueError, TypeError) as exc:
        print(f"Error: invalid coordinates: {exc}", file=sys.stderr)
        sys.exit(1)


def list_catalogs(args) -> int:
    """CLI handler for 'hevelius catalogs'."""
    sort_by = getattr(args, "sort", "entries") or "entries"
    if sort_by not in CATALOGS_SORT_CHOICES:
        print(f"Error: invalid --sort value '{sort_by}'. Use 'entries' or 'name'.", file=sys.stderr)
        return 1

    sort_order = "desc" if sort_by == "entries" else "asc"
    catalogs = fetch_installed_catalogs(sort_by=sort_by, sort_order=sort_order)
    print(render_catalogs_text(catalogs))
    return 0


def find_catalog_objects(args) -> int:
    """CLI handler for 'hevelius catalog'."""
    coords = _validate_ra_dec_pair(getattr(args, "ra", None), getattr(args, "dec", None))

    sort_by = getattr(args, "sort", "name") or "name"
    if sort_by not in OBJECT_SORT_CHOICES:
        print(
            f"Error: invalid --sort value '{sort_by}'. "
            f"Use one of: {', '.join(OBJECT_SORT_CHOICES)}.",
            file=sys.stderr,
        )
        return 1

    sort_order = getattr(args, "sort_order", "asc") or "asc"
    if sort_order not in ("asc", "desc"):
        print("Error: invalid --sort-order. Use 'asc' or 'desc'.", file=sys.stderr)
        return 1

    name = getattr(args, "name", None)
    if name is not None and not str(name).strip():
        name = None

    limit = getattr(args, "limit", None)
    if limit is not None and limit < 1:
        print("Error: --limit must be a positive integer.", file=sys.stderr)
        return 1

    ra_hours = coords[0] if coords else None
    decl = coords[1] if coords else None

    objects = fetch_catalog_objects(
        catalog=getattr(args, "catalog", None),
        constellation=getattr(args, "const", None),
        name=name,
        ra_hours=ra_hours,
        decl=decl,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )
    print(render_objects_text(objects))
    return 0
