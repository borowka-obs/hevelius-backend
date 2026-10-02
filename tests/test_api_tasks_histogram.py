"""Tests for GET /api/tasks/histogram (hevelius.sky_grid)."""

import json
import os
import unittest

from flask_jwt_extended import create_access_token

from hevelius import db
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

    def _get(self, query=""):
        path = "/api/tasks/histogram" + (f"?{query}" if query else "")
        response = self.app.get(path, headers=self.headers)
        return response, json.loads(response.data) if response.status_code == 200 else None

    def _cells_by_coord(self, data):
        return {(c["ra_deg"], c["decl_deg"]): c for c in data["cells"]}

    def _seed_mode_and_default_tasks(self, cnx):
        """A completed cluster near (83, 22) + one south of the equator
        (crossing a negative floor() boundary), plus a same-position task in
        each of the three states that "all tasks" mode must handle:
        state=1 (real, not yet completed - included in 'all', excluded from
        'completed'), state=0 (template) and state=-1 (deleted) - both of
        which must be excluded from *both* modes."""
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
            (900004, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 6, 'd.fits', 83.5, -5.5),
            -- nominal-only (never plate-solved), real state: in 'all', not in 'completed'
            (900005, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 1, NULL, NULL, NULL),
            -- template: excluded from both modes even though it shares 900005's position
            (900006, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, 0, NULL, NULL, NULL),
            -- deleted: excluded from both modes even though it shares 900005's position
            (900007, 1, 1, 'M1', 5.5, 22.0, 60, 'L', 1, -1, NULL, NULL, NULL)
            """,
        )

    @use_repository
    def test_histogram_default_params(self, config):
        """No query params reproduces resolution_deg=1, mode=completed, scope_id=None."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        self._seed_mode_and_default_tasks(cnx)
        cnx.close()

        response, data = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["resolution_deg"], 1)
        self.assertEqual(data["mode"], "completed")
        self.assertIsNone(data["scope_id"])
        self.assertEqual(data["ra_bins"], 360)
        self.assertEqual(data["decl_bins"], 180)
        self.assertEqual(data["ra_unit"], "deg")

        cells = self._cells_by_coord(data)
        self.assertEqual(cells[(83, 22)]["count"], 3)
        self.assertEqual(cells[(83, 22)]["completed_count"], 3)
        self.assertIsNone(cells[(83, 22)]["project_count"])
        # floor(-5.5) == -6, not -5: SQL floor() rounds toward -infinity.
        self.assertEqual(cells[(83, -6)]["count"], 1)
        # The non-completed/template/deleted tasks share bucket (82, 22)
        # (floor(5.5*15)=82); none of them are state=6, so under the
        # default "completed" mode that bucket must not appear at all.
        self.assertNotIn((82, 22), cells)
        self.assertEqual(data["nonempty_cells"], len(data["cells"]))
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_mode_all_excludes_templates_and_deleted(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        self._seed_mode_and_default_tasks(cnx)
        cnx.close()

        response, data = self._get("mode=all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["mode"], "all")

        cells = self._cells_by_coord(data)
        # Completed cluster is unaffected by mode.
        self.assertEqual(cells[(83, 22)]["count"], 3)
        self.assertEqual(cells[(83, 22)]["completed_count"], 3)
        # Bucket (82, 22): only the state=1 task (900005) counts. If the
        # template (900006, state=0) or deleted (900007, state=-1) rows
        # leaked in, count would be 3 instead of 1.
        self.assertEqual(cells[(82, 22)]["count"], 1)
        self.assertEqual(cells[(82, 22)]["completed_count"], 0)
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_resolution_switching(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        db.run_query(
            cnx,
            """
            INSERT INTO tasks (
                task_id, user_id, scope_id, object, ra, decl, exposure,
                filter, binning, state, imagename, he_solved_ra, he_solved_dec
            ) VALUES
            (900101, 1, 1, 'X', 8.0, 10.0, 60, 'L', 1, 6, 'a.fits', 120.4, 10.0),
            (900102, 1, 1, 'X', 8.5, 10.0, 60, 'L', 1, 6, 'b.fits', 127.9, 10.0)
            """,
        )
        cnx.close()

        response, data = self._get("resolution_deg=1")
        self.assertEqual(response.status_code, 200)
        cells = self._cells_by_coord(data)
        self.assertEqual(cells[(120, 10)]["count"], 1)
        self.assertEqual(cells[(127, 10)]["count"], 1)

        response, data = self._get("resolution_deg=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["ra_bins"], 36)
        self.assertEqual(data["decl_bins"], 18)
        cells = self._cells_by_coord(data)
        # Both tasks collapse into the same 10-degree bin.
        self.assertEqual(cells[(120, 10)]["count"], 2)
        self.assertNotIn((127, 10), cells)
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_invalid_resolution(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response, _ = self._get("resolution_deg=3")
        self.assertEqual(response.status_code, 422)
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_scope_filter(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        db.run_query(
            cnx,
            """
            INSERT INTO tasks (
                task_id, user_id, scope_id, object, ra, decl, exposure,
                filter, binning, state, imagename, he_solved_ra, he_solved_dec
            ) VALUES
            (900201, 1, 1, 'X', 13.3, 45.3, 60, 'L', 1, 6, 'a.fits', 200.2, 45.3),
            (900202, 1, 2, 'X', 13.3, 45.3, 60, 'L', 1, 6, 'b.fits', 200.2, 45.3)
            """,
        )
        cnx.close()

        response, data = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._cells_by_coord(data)[(200, 45)]["count"], 2)

        response, data = self._get("scope_id=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["scope_id"], 1)
        self.assertEqual(self._cells_by_coord(data)[(200, 45)]["count"], 1)

        response, data = self._get("scope_id=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._cells_by_coord(data)[(200, 45)]["count"], 1)
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_include_projects_respects_mode(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        db.run_query(
            cnx,
            "INSERT INTO projects (project_id, name, scope_id) VALUES "
            "(900301, 'Test project A', 1), (900302, 'Test project B', 1), (900303, 'Test project C', 1)",
        )
        db.run_query(
            cnx,
            """
            INSERT INTO tasks (
                task_id, user_id, scope_id, object, ra, decl, exposure,
                filter, binning, state, imagename, he_solved_ra, he_solved_dec
            ) VALUES
            (900311, 1, 1, 'X', 16.7, -10.0, 60, 'L', 1, 6, 'a.fits', 250.0, -10.0),
            (900312, 1, 1, 'X', 16.7, -10.0, 60, 'L', 1, 6, 'b.fits', 250.0, -10.0),
            (900313, 1, 1, 'X', 16.7, -10.0, 60, 'L', 1, 6, 'c.fits', 250.0, -10.0),
            -- not completed: only counts toward 'all' mode's project_count
            (900314, 1, 1, 'X', 16.7, -10.0, 60, 'L', 1, 1, NULL, NULL, NULL)
            """,
        )
        db.run_query(
            cnx,
            "INSERT INTO task_projects (task_id, project_id) VALUES "
            "(900311, 900301), (900312, 900301), (900313, 900302), (900314, 900303)",
        )
        cnx.close()

        response, data = self._get("include_projects=true")
        self.assertEqual(response.status_code, 200)
        cell = self._cells_by_coord(data)[(250, -10)]
        self.assertEqual(cell["count"], 3)
        self.assertEqual(cell["completed_count"], 3)
        # Projects 900301 and 900302 both have completed tasks here; 900303's
        # only task (900314) isn't completed, so it doesn't count.
        self.assertEqual(cell["project_count"], 2)

        response, data = self._get("mode=all&include_projects=true")
        self.assertEqual(response.status_code, 200)
        cell = self._cells_by_coord(data)[(250, -10)]
        self.assertEqual(cell["count"], 4)
        self.assertEqual(cell["completed_count"], 3)
        # Under 'all' mode, 900303 (via the non-completed 900314) counts too.
        self.assertEqual(cell["project_count"], 3)

        response, data = self._get()  # include_projects defaults to false
        self.assertIsNone(self._cells_by_coord(data)[(250, -10)]["project_count"])
        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_histogram_requires_auth(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        bare = self.app.get("/api/tasks/histogram")
        self.assertIn(bare.status_code, (401, 422))
        os.environ.pop("HEVELIUS_DB_NAME", None)
