"""Unit tests for asteroid CLI helpers (cache age, download skip, load path)."""

import gzip
import io
import os
import tempfile
import time
import unittest
from argparse import Namespace
from unittest.mock import patch

from hevelius import cmd_asteroid as asteroid


class TestMpcorbCacheInfo(unittest.TestCase):
    """Tests for mpcorb_cache_info freshness metadata."""

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(asteroid.mpcorb_cache_info(os.path.join(tmp, "missing.DAT")))

    def test_fresh_and_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "MPCORB.DAT")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x" * 200)

            info = asteroid.mpcorb_cache_info(path)
            self.assertIsNotNone(info)
            self.assertTrue(info["fresh"])
            self.assertEqual(info["size_bytes"], 200)
            self.assertEqual(info["path"], os.path.abspath(path))

            # Age the file beyond the freshness window.
            old = time.time() - (asteroid.MPCORB_MAX_AGE_DAYS + 1) * 86400
            os.utime(path, (old, old))
            info = asteroid.mpcorb_cache_info(path)
            self.assertFalse(info["fresh"])
            self.assertGreater(info["age_seconds"], asteroid.MPCORB_MAX_AGE_DAYS * 86400)


class TestDownloadMpcorb(unittest.TestCase):
    """Tests for download_mpcorb skip / force / error logging."""

    def test_skips_when_fresh_and_logs_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "MPCORB.DAT")
            with open(path, "w", encoding="utf-8") as f:
                f.write("cached")

            buf = io.StringIO()
            with patch.object(asteroid, "_cache_dir", return_value=tmp), \
                 patch.object(asteroid, "_cache_path", return_value=path), \
                 patch.object(asteroid.urllib.request, "urlretrieve") as retrieve, \
                 patch("sys.stdout", buf):
                result = asteroid.download_mpcorb(force=False)

            self.assertEqual(result, path)
            retrieve.assert_not_called()
            out = buf.getvalue()
            self.assertIn("Skipping MPC download", out)
            self.assertIn("younger than", out)
            self.assertIn("--force", out)

    def test_redownloads_when_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "MPCORB.DAT")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old")
            old = time.time() - (asteroid.MPCORB_MAX_AGE_DAYS + 1) * 86400
            os.utime(path, (old, old))

            def fake_retrieve(_url, dest):
                with gzip.open(dest, "wb") as gz:
                    gz.write(b"new-content")

            buf = io.StringIO()
            with patch.object(asteroid, "_cache_dir", return_value=tmp), \
                 patch.object(asteroid, "_cache_path", return_value=path), \
                 patch.object(asteroid.urllib.request, "urlretrieve", side_effect=fake_retrieve), \
                 patch("sys.stdout", buf):
                result = asteroid.download_mpcorb(force=False)

            self.assertEqual(result, path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"new-content")
            out = buf.getvalue()
            self.assertIn("older than", out)
            self.assertIn("Downloading", out)

    def test_force_redownloads_even_when_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "MPCORB.DAT")
            with open(path, "w", encoding="utf-8") as f:
                f.write("fresh")

            def fake_retrieve(_url, dest):
                with gzip.open(dest, "wb") as gz:
                    gz.write(b"forced")

            buf = io.StringIO()
            with patch.object(asteroid, "_cache_dir", return_value=tmp), \
                 patch.object(asteroid, "_cache_path", return_value=path), \
                 patch.object(asteroid.urllib.request, "urlretrieve", side_effect=fake_retrieve), \
                 patch("sys.stdout", buf):
                result = asteroid.download_mpcorb(force=True)

            self.assertEqual(result, path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"forced")
            self.assertIn("--force", buf.getvalue())

    def test_logs_download_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "MPCORB.DAT")
            err = asteroid.urllib.error.URLError("network down")

            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch.object(asteroid, "_cache_dir", return_value=tmp), \
                 patch.object(asteroid, "_cache_path", return_value=path), \
                 patch.object(asteroid.urllib.request, "urlretrieve", side_effect=err), \
                 patch("sys.stdout", buf_out), \
                 patch("sys.stderr", buf_err):
                with self.assertRaises(asteroid.urllib.error.URLError):
                    asteroid.download_mpcorb(force=True)

            self.assertIn("failed to download", buf_err.getvalue())


class TestAsteroidsLoad(unittest.TestCase):
    """Tests for the asteroid load CLI entry point."""

    def test_missing_file_returns_error(self):
        args = Namespace(file="/no/such/MPCORB.DAT", limit=None)
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            rc = asteroid.asteroids_load(args)
        self.assertEqual(rc, 1)
        self.assertIn("MPCORB not found", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
