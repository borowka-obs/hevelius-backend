"""Tests for `hevelius doctor` (hevelius.cli.doctor)."""

import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.dbtest import use_repository
from hevelius.cli import doctor


class TestPureChecks(unittest.TestCase):
    """Checks that don't need a database or filesystem log directory."""

    def test_check_config_from_file(self):
        meta = {
            "base_source": "file",
            "base_config_path": "/etc/hevelius/hevelius.yaml",
            "environment_overrides": [],
        }
        status, message = doctor.check_config({}, meta)
        self.assertEqual(status, doctor.OK)
        self.assertIn("/etc/hevelius/hevelius.yaml", message)

    def test_check_config_defaults_warns(self):
        meta = {"base_source": "defaults", "base_config_path": None, "environment_overrides": ["HEVELIUS_DB_HOST"]}
        status, message = doctor.check_config({}, meta)
        self.assertEqual(status, doctor.WARN)
        self.assertIn("built-in defaults", message)
        self.assertIn("HEVELIUS_DB_HOST", message)

    def test_check_jwt_unset(self):
        status, _ = doctor.check_jwt({"jwt": {"secret-key": None}})
        self.assertEqual(status, doctor.FAIL)

    def test_check_jwt_example_value(self):
        status, message = doctor.check_jwt({"jwt": {"secret-key": "your-secret-key-here"}})
        self.assertEqual(status, doctor.FAIL)
        self.assertIn("example", message)

    def test_check_jwt_too_short(self):
        status, _ = doctor.check_jwt({"jwt": {"secret-key": "short"}})
        self.assertEqual(status, doctor.WARN)

    def test_check_jwt_ok(self):
        status, _ = doctor.check_jwt({"jwt": {"secret-key": "x" * 40}})
        self.assertEqual(status, doctor.OK)

    def test_check_web_url_unset(self):
        status, _ = doctor.check_web_url({"web": {"base-url": None}})
        self.assertEqual(status, doctor.FAIL)

    def test_check_web_url_example(self):
        status, _ = doctor.check_web_url({"web": {"base-url": "https://hevelius.example.com"}})
        self.assertEqual(status, doctor.WARN)

    def test_check_web_url_default(self):
        status, _ = doctor.check_web_url({"web": {"base-url": "http://localhost:3000"}})
        self.assertEqual(status, doctor.WARN)

    def test_check_web_url_ok(self):
        status, _ = doctor.check_web_url({"web": {"base-url": "https://obs.example.org"}})
        self.assertEqual(status, doctor.OK)

    def test_check_smtp_not_configured(self):
        status, message = doctor.check_smtp({"smtp": {"host": None}})
        self.assertEqual(status, doctor.WARN)
        self.assertIn("not set", message)

    def test_check_smtp_ok(self):
        status, _ = doctor.check_smtp({
            "smtp": {"host": "smtp.example.com", "port": 587, "from-addr": "a@example.com",
                     "username": "u", "password": "p"},
        })
        self.assertEqual(status, doctor.OK)

    def test_check_smtp_bad_port(self):
        status, message = doctor.check_smtp({
            "smtp": {"host": "smtp.example.com", "port": 99999, "from-addr": "a@example.com"},
        })
        self.assertEqual(status, doctor.WARN)
        self.assertIn("port", message)

    def test_check_smtp_bad_from_addr(self):
        status, message = doctor.check_smtp({
            "smtp": {"host": "smtp.example.com", "port": 587, "from-addr": "not-an-email"},
        })
        self.assertEqual(status, doctor.WARN)
        self.assertIn("from-addr", message)

    def test_check_smtp_lopsided_credentials(self):
        status, message = doctor.check_smtp({
            "smtp": {"host": "smtp.example.com", "port": 587, "from-addr": "a@example.com", "username": "u"},
        })
        self.assertEqual(status, doctor.WARN)
        self.assertIn("username and password", message)

    def test_check_startup_ok(self):
        status, message = doctor.check_startup()
        self.assertEqual(status, doctor.OK)
        self.assertIn("Python", message)

    def test_check_startup_missing_module(self):
        with patch("builtins.__import__", side_effect=ImportError):
            status, message = doctor.check_startup()
        self.assertEqual(status, doctor.FAIL)
        self.assertIn("Missing required", message)


class TestLogChecks(unittest.TestCase):

    def test_check_logs_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope")
            status, message, files = doctor.check_logs({"logs": {"path": missing}})
            self.assertEqual(status, doctor.WARN)
            self.assertEqual(files, [])
            self.assertIn(missing, message)

    def test_check_logs_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "error.log"), "w", encoding="utf-8").close()
            status, _message, files = doctor.check_logs({"logs": {"path": tmp}})
            self.assertEqual(status, doctor.OK)
            self.assertEqual(len(files), 1)

    def test_check_log_errors_none_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "error.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write("all quiet\nnothing to see here\n")
            status, _message = doctor.check_log_errors([path])
            self.assertEqual(status, doctor.OK)

    def test_check_log_errors_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "error.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write("INFO fine\nERROR kaboom\nCRITICAL also bad\n")
            status, message = doctor.check_log_errors([path])
            self.assertEqual(status, doctor.WARN)
            self.assertIn("2 error-like", message)

    def test_check_log_errors_skipped_when_no_files(self):
        status, message = doctor.check_log_errors([])
        self.assertEqual(status, doctor.INFO)
        self.assertIn("Skipped", message)

    def test_latest_migration_version(self):
        # Uses the real db/ directory checked into the repo.
        self.assertEqual(doctor.latest_migration_version("db"), 25)

    def test_latest_migration_version_missing_dir(self):
        self.assertIsNone(doctor.latest_migration_version("/no/such/dir"))


class TestMailCheck(unittest.TestCase):

    def test_mail_check_no_smtp_host(self):
        with patch.object(doctor, "load_config", return_value={"smtp": {"host": None}}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = doctor.mail_check("nobody@example.com", color=False)
            self.assertEqual(rc, 1)
            self.assertIn("FAIL", buf.getvalue())

    def test_mail_check_send_success(self):
        cfg = {"smtp": {"host": "smtp.example.com", "port": 587}}
        with patch.object(doctor, "load_config", return_value=cfg), \
             patch.object(doctor, "send_email", return_value=True) as send:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = doctor.mail_check("nobody@example.com", color=False)
            self.assertEqual(rc, 0)
            self.assertIn("OK", buf.getvalue())
            send.assert_called_once()

    def test_mail_check_send_raises(self):
        cfg = {"smtp": {"host": "smtp.example.com", "port": 587}}
        with patch.object(doctor, "load_config", return_value=cfg), \
             patch.object(doctor, "send_email", side_effect=OSError("boom")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = doctor.mail_check("nobody@example.com", color=False)
            self.assertEqual(rc, 1)
            self.assertIn("boom", buf.getvalue())


class TestDoctorDb(unittest.TestCase):
    """End-to-end checks that need a real (migrated) database."""

    @use_repository(load_test_data=None)
    def test_check_database_and_schema_ok(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        try:
            from hevelius.config import load_config
            full_config = load_config()
            status, _message = doctor.check_database(full_config)
            self.assertEqual(status, doctor.OK)

            schema_status, schema_message = doctor.check_schema(True)
            self.assertEqual(schema_status, doctor.OK)
            self.assertIn("up to date", schema_message)
        finally:
            os.environ.pop("HEVELIUS_DB_NAME", None)

    @use_repository(load_test_data=None)
    def test_doctor_end_to_end_returns_failure_on_bad_settings(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        # Force a deterministic FAIL regardless of ambient env or hevelius.yaml:
        # JWT_SECRET_KEY overrides file config (empty would not — load_config only
        # applies truthy env values), so set the documented example placeholder.
        leaky_env = ["JWT_SECRET_KEY", "HEVELIUS_WEB_BASE_URL", "HEVELIUS_SMTP_HOST"]
        saved = {k: os.environ.pop(k, None) for k in leaky_env}
        os.environ["JWT_SECRET_KEY"] = doctor._JWT_EXAMPLE_SECRET
        try:
            args = Namespace(mail_check=None, no_color=True)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = doctor.doctor(args)
            out = buf.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("Database", out)
            self.assertIn("DB schema is up to date", out)
            self.assertIn("JWT secret", out)
            self.assertIn("example placeholder", out)
        finally:
            os.environ.pop("HEVELIUS_DB_NAME", None)
            os.environ.pop("JWT_SECRET_KEY", None)
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
