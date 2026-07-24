"""Tests for GET /api/tasks/histogram."""

import json
import os
import unittest

from flask_jwt_extended import create_access_token

from hevelius import db, stats
from hevelius.api import app
from tests.dbtest import use_repository


class TestTasksHistogram(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        with app.app_context():
            self.test_token = create_access_token(
                identity=1,
                additional_claims={"permissions": 1, "username": "test_user"},
            )
            self.headers = {
                "Authorization": f"Bearer {self.test_token}",
                "Content-Type": "application/json",
            }

    def _seed_solved_tasks(self, cnx):
        """Insert a few completed plate-solved frames at known sky positions."""
        db.run_query(
            cnx,
            """
            INSERT INTO tasks (
                task_id, user_id, scope_id, object, ra, decl, exposure,
                filter, binning, state, imagename, he_solved_ra, he_solved_dec
            ) VALUES
            (900001, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, 'a.fits', 83.2, 22.1),
            (900002, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, 'b.fits', 83.7, 22.4),
            (900003, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, 'c.fits', 83.1, 22.9),
            (900004, 1, 1, 'M42', 5.5, -5.0, 60, 'L', 1, 6, 'd.fits', 83.5, -5.2),
            -- excluded: not done
            (900005, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 1, 'e.fits', 83.0, 22.0),
            -- excluded: no imagename
            (900006, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, NULL, 83.0, 22.0),
            -- excluded: no solved coords
            (900007, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, 'f.fits', NULL, NULL)
            """,
        )

    @use_repository
    def test_sky_histogram_payload(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        self._seed_solved_tasks(cnx)
        payload = stats.sky_histogram_payload(cnx)
        cnx.close()

        self.assertEqual(payload["resolution_deg"], 1)
        self.assertEqual(payload["ra_bins"], 360)
        self.assertEqual(payload["decl_bins"], 180)
        self.assertEqual(payload["ra_unit"], "deg")
        # 3 at (83,22) + 1 at (83,-5); plus any from fixture data
        self.assertGreaterEqual(payload["total_frames"], 4)

        cells = {(c["ra_deg"], c["decl_deg"]): c["count"] for c in payload["cells"]}
        self.assertGreaterEqual(cells.get((83, 22), 0), 3)
        self.assertGreaterEqual(cells.get((83, -5), 0), 1)
        self.assertEqual(payload["nonempty_cells"], len(payload["cells"]))
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_api_tasks_histogram(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        self._seed_solved_tasks(cnx)
        cnx.close()

        response = self.app.get("/api/tasks/histogram", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data["ra_unit"], "deg")
        self.assertGreaterEqual(data["total_frames"], 4)
        self.assertIsInstance(data["cells"], list)
        self.assertTrue(any(c["ra_deg"] == 83 and c["decl_deg"] == 22 for c in data["cells"]))

        # Auth required
        bare = self.app.get("/api/tasks/histogram")
        self.assertIn(bare.status_code, (401, 422))
        os.environ.pop("HEVELIUS_DB_NAME", None)
