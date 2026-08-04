"""
Tests telescope timezone support: hevelius.equipment.list_timezones,
add_telescope/edit_telescope --timezone validation and persistence.
"""

import contextlib
import io
import os
import unittest

from hevelius import db
from hevelius.equipment import (
    _is_valid_timezone,
    list_timezones,
    add_telescope,
    edit_telescope,
)
from tests.dbtest import use_repository


class TestTimezoneValidation(unittest.TestCase):
    """Pure logic, no DB: timezone name validation and the `timezones` lookup command."""

    def test_is_valid_timezone(self):
        """Valid/invalid IANA names are accepted/rejected."""
        self.assertTrue(_is_valid_timezone("Europe/Warsaw"))
        self.assertTrue(_is_valid_timezone("UTC"))
        self.assertFalse(_is_valid_timezone("Not/AZone"))
        self.assertFalse(_is_valid_timezone(""))

    def test_list_timezones_filter(self):
        """`telescope timezones --filter` narrows to matching names, case-insensitively."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            list_timezones("warsaw")
        output = buf.getvalue()
        self.assertIn("Europe/Warsaw", output)
        self.assertIn("1 timezone(s) matching 'warsaw'", output)

    def test_list_timezones_no_match(self):
        """A filter matching nothing prints a clear message instead of an empty list."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            list_timezones("nonexistent-zone-zzz")
        output = buf.getvalue()
        self.assertIn("No timezones matching", output)

    def test_add_telescope_rejects_invalid_timezone_without_db(self):
        """Validation happens before any DB connection is attempted."""
        result = add_telescope("Should Not Be Created", timezone="Not/AZone")
        self.assertIsNone(result)

    def test_edit_telescope_rejects_invalid_timezone_without_db(self):
        """Same early-validation guarantee for edit as for add."""
        result = edit_telescope(1, timezone="Not/AZone")
        self.assertFalse(result)


class TestTelescopeTimezoneDb(unittest.TestCase):
    """DB-backed: add_telescope/edit_telescope actually persist --timezone."""

    @use_repository
    def test_add_telescope_with_timezone(self, config):
        """A valid --timezone is stored as given."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            scope_id = add_telescope("CLI TZ Test Scope", timezone="Europe/Warsaw")
            self.assertIsNotNone(scope_id)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT timezone FROM telescopes WHERE scope_id = %s", (scope_id,))
            conn.close()
            self.assertEqual(rows[0][0], "Europe/Warsaw")
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)

    @use_repository
    def test_add_telescope_without_timezone_defaults_to_utc(self, config):
        """Omitting --timezone falls back to the DB column default ('UTC')."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            scope_id = add_telescope("CLI TZ Default Scope")
            self.assertIsNotNone(scope_id)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT timezone FROM telescopes WHERE scope_id = %s", (scope_id,))
            conn.close()
            self.assertEqual(rows[0][0], "UTC")
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)

    @use_repository
    def test_edit_telescope_updates_timezone(self, config):
        """edit_telescope(timezone=...) updates an existing telescope's zone."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            scope_id = add_telescope("CLI TZ Edit Scope")
            self.assertIsNotNone(scope_id)
            ok = edit_telescope(scope_id, timezone="America/Santiago")
            self.assertTrue(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT timezone FROM telescopes WHERE scope_id = %s", (scope_id,))
            conn.close()
            self.assertEqual(rows[0][0], "America/Santiago")
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)

    @use_repository
    def test_edit_telescope_invalid_timezone_leaves_db_unchanged(self, config):
        """A rejected --timezone on edit doesn't touch the stored value."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            scope_id = add_telescope("CLI TZ Unchanged Scope", timezone="Europe/Warsaw")
            self.assertIsNotNone(scope_id)
            ok = edit_telescope(scope_id, timezone="Not/AZone")
            self.assertFalse(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT timezone FROM telescopes WHERE scope_id = %s", (scope_id,))
            conn.close()
            self.assertEqual(rows[0][0], "Europe/Warsaw")
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)


if __name__ == "__main__":
    unittest.main()
