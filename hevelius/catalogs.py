"""Catalog listing and object search (shared by CLI and API)."""

from typing import Any, Dict, List, Optional

from hevelius import db

CATALOGS_SORT_CHOICES = ("entries", "name")
OBJECT_SORT_CHOICES = ("catalog", "name", "ra", "decl", "const", "type", "magn")


def catalog_row_to_dict(row) -> Dict[str, Any]:
    return {
        "name": row[0],
        "shortname": row[1],
        "object_count": row[2],
    }


def object_row_to_dict(row) -> Dict[str, Any]:
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
    return [catalog_row_to_dict(row) for row in rows]


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
    return [object_row_to_dict(row) for row in rows]
