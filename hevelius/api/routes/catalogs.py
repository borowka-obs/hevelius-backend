import logging

from flask.views import MethodView
from flask_jwt_extended import jwt_required


from hevelius import db
from hevelius.catalogs import fetch_installed_catalogs, object_row_to_dict
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    CatalogsInstalledRequestSchema,
    CatalogsInstalledResponseSchema,
    ObjectSearchRequestSchema,
    ObjectSearchResponseSchema,
    ObjectsListRequestSchema,
    ObjectsListResponseSchema,
)

logger = logging.getLogger(__name__)


@blp.route("/catalogs")
class CatalogsInstalledResource(MethodView):
    @jwt_required()
    @blp.arguments(CatalogsInstalledRequestSchema, location="query")
    @blp.response(200, CatalogsInstalledResponseSchema)
    def get(self, args):
        """List installed catalogs with object counts."""
        sort_by = args.get('sort', 'entries')
        sort_order = 'desc' if sort_by == 'entries' else 'asc'
        return {'catalogs': fetch_installed_catalogs(sort_by=sort_by, sort_order=sort_order)}


@blp.route("/catalogs/search")
class ObjectSearchResource(MethodView):
    @jwt_required()
    @blp.arguments(ObjectSearchRequestSchema, location="query")
    @blp.response(200, ObjectSearchResponseSchema)
    def get(self, args):
        """Search for astronomical objects by name
        Returns a list of objects matching the search query
        """
        query = args['query']
        limit = args['limit']

        # Build the search query
        search_query = """
            SELECT object_id, name, ra, decl, descr, comment, type, epoch, const,
                   magn, x, y, altname, distance, catalog
            FROM objects
            WHERE name ILIKE %s OR altname ILIKE %s
            ORDER BY name
            LIMIT %s
        """

        # Add wildcards for partial matching
        search_pattern = f"%{query}%"

        cnx = db.connect()
        results = db.run_query(cnx, search_query, (search_pattern, search_pattern, limit))
        cnx.close()

        return {"objects": [object_row_to_dict(row) for row in results]}


@blp.route("/catalogs/list")
class ObjectsListResource(MethodView):
    @jwt_required()
    @blp.arguments(ObjectsListRequestSchema, location="query")
    @blp.response(200, ObjectsListResponseSchema)
    def get(self, args):
        """Get list of astronomical objects with paging, sorting, and filtering"""
        return self._get_objects(args)

    @jwt_required()
    @blp.arguments(ObjectsListRequestSchema)
    @blp.response(200, ObjectsListResponseSchema)
    def post(self, args):
        """Get list of astronomical objects with paging, sorting, and filtering"""
        return self._get_objects(args)

    def _get_objects(self, args):
        """Helper method to get objects based on filters, sorting, and paging"""
        page = args.get('page', 1)
        per_page = args.get('per_page', 100)
        offset = (page - 1) * per_page

        cnx = db.connect()
        total_count = db.catalog_objects_count(
            cnx,
            catalog=args.get('catalog'),
            constellation=args.get('constellation'),
            name=args.get('name'),
            ra_hours=args.get('ra'),
            decl=args.get('decl'),
            proximity=args.get('proximity', 1.0),
        )
        objects_list = db.catalog_objects_search(
            cnx,
            catalog=args.get('catalog'),
            constellation=args.get('constellation'),
            name=args.get('name'),
            ra_hours=args.get('ra'),
            decl=args.get('decl'),
            proximity=args.get('proximity', 1.0),
            sort_by=args.get('sort_by', 'name'),
            sort_order=args.get('sort_order', 'asc'),
            limit=per_page,
            offset=offset,
        )
        cnx.close()

        logger.info(
            "Catalog list: returned %d entries (page %d, total matching: %d)",
            len(objects_list), page, total_count
        )

        total_pages = (total_count + per_page - 1) // per_page if per_page else 0

        return {
            "objects": [object_row_to_dict(obj) for obj in objects_list],
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "pages": total_pages,
        }
