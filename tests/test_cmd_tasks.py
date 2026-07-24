"""Tests for `hevelius task list` (DB helpers + CLI)."""

import io
import os
import unittest
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr

from tests.dbtest import use_repository
from hevelius import db
from hevelius.cli.tasks import list_tasks


class TestTasksListDb(unittest.TestCase):
    """DB-layer tests for tasks_count / tasks_list."""

    @use_repository
    def test_count_and_default_order(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        try:
            total = db.tasks_count(cnx)
            self.assertEqual(total, 11)

            rows = db.tasks_list(cnx, sort_by="task_id", sort_order="desc", limit=3)
            self.assertEqual(len(rows), 3)
            ids = [r[0] for r in rows]
            self.assertEqual(ids, sorted(ids, reverse=True))
            self.assertEqual(ids[0], 87775)

            # Columns: task_id, state_id, state_name, object, login, ...
            self.assertEqual(rows[0][3], "Z Peg")
            self.assertEqual(rows[0][4], "tomek")
            self.assertIsNotNone(rows[0][2])  # state name
        finally:
            cnx.close()
            os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_filters(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        try:
            self.assertEqual(db.tasks_count(cnx, object_name="NGC"), 1)
            rows = db.tasks_list(cnx, object_name="NGC")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], 800)
            self.assertIn("NGC", rows[0][3])

            self.assertEqual(db.tasks_count(cnx, user_login="tomek"), 6)
            self.assertEqual(db.tasks_count(cnx, user_id=1), 5)
            self.assertEqual(db.tasks_count(cnx, scope_id=2), 4)
            self.assertEqual(db.tasks_count(cnx, project_id=1), 3)

            # State DONE = 6 appears in test data for completed frames
            done = db.tasks_count(cnx, state=6)
            self.assertGreaterEqual(done, 1)
            self.assertEqual(db.task_state_id_by_name(cnx, "DONE"), 6)
            self.assertIsNone(db.task_state_id_by_name(cnx, "NOSUCH"))
        finally:
            cnx.close()
            os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_pagination(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        cnx = db.connect()
        try:
            page1 = db.tasks_list(cnx, sort_by="task_id", sort_order="asc", limit=4, offset=0)
            page2 = db.tasks_list(cnx, sort_by="task_id", sort_order="asc", limit=4, offset=4)
            self.assertEqual(len(page1), 4)
            self.assertEqual(len(page2), 4)
            ids1 = [r[0] for r in page1]
            ids2 = [r[0] for r in page2]
            self.assertTrue(max(ids1) < min(ids2))
            self.assertEqual(len(set(ids1) & set(ids2)), 0)
        finally:
            cnx.close()
            os.environ.pop("HEVELIUS_DB_NAME", None)


class TestTasksListCli(unittest.TestCase):
    """CLI tests for list_tasks."""

    def _args(self, **kwargs):
        defaults = dict(
            limit=100,
            offset=0,
            sort_by="task_id",
            sort_order="desc",
            object=None,
            user=None,
            user_id=None,
            scope_id=None,
            state=None,
            project_id=None,
            no_color=True,
        )
        defaults.update(kwargs)
        return Namespace(**defaults)

    @use_repository
    def test_list_defaults_and_footer(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(limit=5))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("showing 1–5 of 11", out)
        self.assertIn("more", out)
        self.assertIn("--offset 5", out)
        self.assertIn("87775", out)
        self.assertLess(out.index("87775"), out.index("70556"))

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(limit=5, offset=10))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("showing 11–11 of 11", out)
        self.assertNotIn("more", out)

        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_list_filters(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(object="NGC"))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("of 1", out)
        self.assertIn("800", out)
        self.assertIn("NGC", out)
        self.assertNotIn("Z Peg", out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(user="tomek"))
        self.assertEqual(rc, 0)
        self.assertIn("of 6", buf.getvalue())

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(state="DONE", limit=100))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("DONE", out)
        self.assertRegex(out, r"of \d+")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(project_id=1))
        self.assertEqual(rc, 0)
        self.assertIn("of 3", buf.getvalue())

        os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository
    def test_list_empty_and_invalid(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_tasks(self._args(object="NoSuchObjectXYZ"))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("of 0", out)
        self.assertIn("no matches", out)

        err = io.StringIO()
        with redirect_stderr(err):
            rc = list_tasks(self._args(state="NOTASTATE"))
        self.assertEqual(rc, 1)
        self.assertIn("unknown task state", err.getvalue())

        err = io.StringIO()
        with redirect_stderr(err):
            rc = list_tasks(self._args(limit=0))
        self.assertEqual(rc, 1)
        self.assertIn("--limit", err.getvalue())

        err = io.StringIO()
        with redirect_stderr(err):
            rc = list_tasks(self._args(sort_by="notafield"))
        self.assertEqual(rc, 1)
        self.assertIn("--sort-by", err.getvalue())

        os.environ.pop("HEVELIUS_DB_NAME", None)
