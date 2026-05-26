import io
import os
import unittest
from argparse import Namespace
from unittest.mock import patch

from tests.dbtest import use_repository
from hevelius import db
from hevelius.cmd_catalogs import (
    fetch_catalog_objects,
    fetch_installed_catalogs,
    find_catalog_objects,
    list_catalogs,
    render_catalogs_text,
    render_objects_text,
)


def _seed_catalogs(cnx):
    db.run_query(
        cnx,
        """
        INSERT INTO catalogs (name, shortname, filename, descr, url, version)
        VALUES
        ('Test New General Catalogue', 'TNGC', 'ngc.dat', 'NGC', 'http://example.com/ngc', '1.0'),
        ('Test Messier Catalogue', 'TM', 'm.dat', 'Messier', 'http://example.com/m', '1.0')
        """,
    )
    db.run_query(
        cnx,
        """
        INSERT INTO objects (name, ra, decl, descr, type, catalog, const, magn, altname)
        VALUES
        ('TNGC7000', 20.99, 44.37, 'North America Nebula', 'EN', 'TNGC', 'Cyg', 4.0, '7000'),
        ('TNGC7001', 21.00, 44.45, 'Spiral Galaxy', 'G', 'TNGC', 'Cyg', 13.0, NULL),
        ('TM31', 0.71, 41.27, 'Andromeda Galaxy', 'G', 'TM', 'And', 3.4, NULL),
        ('TM8', 18.06, -24.38, 'Lagoon Nebula', 'EN', 'TM', 'Sgr', 6.0, NULL)
        """,
    )


class TestCmdCatalogs(unittest.TestCase):
    @use_repository
    def test_fetch_installed_catalogs_sort_entries(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        catalogs = fetch_installed_catalogs(sort_by="entries")
        test_catalogs = [c for c in catalogs if c["shortname"] in ("TNGC", "TM")]
        self.assertEqual(len(test_catalogs), 2)
        self.assertTrue(all(c["object_count"] == 2 for c in test_catalogs))
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_fetch_installed_catalogs_sort_name(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        catalogs = fetch_installed_catalogs(sort_by="name", sort_order="asc")
        names = [c["name"].lower() for c in catalogs]
        self.assertEqual(names, sorted(names))
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_fetch_catalog_objects_filters(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        by_catalog = fetch_catalog_objects(catalog="TNGC")
        self.assertEqual(len(by_catalog), 2)
        self.assertTrue(all(o["catalog"] == "TNGC" for o in by_catalog))

        by_name = fetch_catalog_objects(name="7000")
        self.assertGreaterEqual(len(by_name), 1)
        self.assertIn("TNGC7000", {o["name"] for o in by_name})

        by_const = fetch_catalog_objects(constellation="Sgr")
        self.assertEqual(len(by_const), 1)
        self.assertEqual(by_const[0]["name"], "TM8")

        limited = fetch_catalog_objects(sort_by="name", limit=2)
        self.assertEqual(len(limited), 2)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_fetch_catalog_objects_coords(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        # TM31 is near RA 0h 43m, Dec +41°
        nearby = fetch_catalog_objects(ra_hours=0.71, decl=41.27, proximity=2.0)
        names = {o["name"] for o in nearby}
        self.assertIn("TM31", names)
        os.environ.pop("HEVELIUS_DB_NAME")

    def test_render_catalogs_text_empty(self):
        self.assertEqual(render_catalogs_text([]), "No catalogs found.")

    def test_render_objects_text(self):
        text = render_objects_text([
            {
                "object_id": 1,
                "name": "M31",
                "ra": 0.71,
                "decl": 41.27,
                "descr": "Andromeda",
                "comment": None,
                "type": "G",
                "epoch": None,
                "const": "And",
                "magn": 3.4,
                "x": None,
                "y": None,
                "altname": None,
                "distance": None,
                "catalog": "M",
            }
        ])
        self.assertIn("M31", text)
        self.assertIn("Andromeda", text)

    @use_repository
    def test_list_catalogs_cli(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        args = Namespace(sort="entries")
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = list_catalogs(args)
        self.assertEqual(rc, 0)
        self.assertIn("TNGC", out.getvalue())
        self.assertIn("Objects", out.getvalue())
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_find_catalog_objects_cli(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect(config)
        _seed_catalogs(cnx)
        cnx.close()

        args = Namespace(
            name="TM31",
            catalog=None,
            const=None,
            ra=None,
            dec=None,
            sort="name",
            sort_order="asc",
            limit=None,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = find_catalog_objects(args)
        self.assertEqual(rc, 0)
        self.assertIn("TM31", out.getvalue())
        os.environ.pop("HEVELIUS_DB_NAME")

    def test_find_catalog_objects_ra_dec_validation(self):
        args = Namespace(
            name=None,
            catalog=None,
            const=None,
            ra="12 00 00",
            dec=None,
            sort="name",
            sort_order="asc",
            limit=None,
        )
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                find_catalog_objects(args)


if __name__ == "__main__":
    unittest.main()
