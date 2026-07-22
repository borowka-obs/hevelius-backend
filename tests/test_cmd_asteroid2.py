"""Unit tests for MPCORB parsing and asteroid visibility helpers."""

import unittest

from astropy.coordinates import EarthLocation
from astropy import units as u

from hevelius import cmd_asteroid


def _mpcorb_line(designation: str, H: str = " 3.34", G: str = " 0.15",
                 epoch: str = "K25A2",
                 M: str = " 10.00000", peri: str = " 73.00000",
                 node: str = " 80.00000", inc: str = " 10.00000",
                 e: str = " 0.0800000", n: str = " 0.21400000",
                 a: str = "  2.7600000",
                 readable: str = "") -> str:
    """Build a minimal fixed-width MPCORB line (>= 104 chars; 194+ with readable)."""
    # Columns are 1-based in the MPC docs; slices below are 0-based.
    length = 194 if readable else 104
    line = [" "] * length
    des = designation.ljust(7)[:7]
    line[0:7] = list(des)
    line[8:13] = list(H.rjust(5)[:5])
    line[14:19] = list(G.rjust(5)[:5])
    line[20:25] = list(epoch.ljust(5)[:5])
    line[26:35] = list(M.rjust(9)[:9])
    line[37:46] = list(peri.rjust(9)[:9])
    line[48:57] = list(node.rjust(9)[:9])
    line[59:68] = list(inc.rjust(9)[:9])
    line[70:79] = list(e.rjust(9)[:9])
    line[80:91] = list(n.rjust(11)[:11])
    line[92:103] = list(a.rjust(11)[:11])
    if readable:
        line[166:194] = list(readable.ljust(28)[:28])
    return "".join(line)


class TestUnpackPermanentNumber(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(cmd_asteroid._unpack_permanent_number("00001"), 1)
        self.assertEqual(cmd_asteroid._unpack_permanent_number("00433"), 433)
        self.assertEqual(cmd_asteroid._unpack_permanent_number("10000"), 10000)
        self.assertEqual(cmd_asteroid._unpack_permanent_number("99999"), 99999)
        # Trailing spaces from the 7-char MPCORB field
        self.assertEqual(cmd_asteroid._unpack_permanent_number("00001  "), 1)

    def test_letter_coded_numbers(self):
        # A0345 → 10*10000 + 345 = 100345
        self.assertEqual(cmd_asteroid._unpack_permanent_number("A0345"), 100345)
        # a0017 → 36*10000 + 17 = 360017
        self.assertEqual(cmd_asteroid._unpack_permanent_number("a0017"), 360017)
        # K3289 → 20*10000 + 3289 = 203289
        self.assertEqual(cmd_asteroid._unpack_permanent_number("K3289"), 203289)
        self.assertEqual(cmd_asteroid._unpack_permanent_number("A0001"), 100001)

    def test_tilde_base62_numbers(self):
        self.assertEqual(cmd_asteroid._unpack_permanent_number("~0000"), 620000)
        self.assertEqual(cmd_asteroid._unpack_permanent_number("~000z"), 620061)
        # ~AZaz = 10*62^3 + 35*62^2 + 36*62 + 61 = 2520113 → 3140113
        self.assertEqual(cmd_asteroid._unpack_permanent_number("~AZaz"), 3140113)

    def test_provisional_returns_none(self):
        self.assertIsNone(cmd_asteroid._unpack_permanent_number("K25A00A"))
        self.assertIsNone(cmd_asteroid._unpack_permanent_number("J98S53D"))
        self.assertIsNone(cmd_asteroid._unpack_permanent_number("PLS2040"))
        self.assertIsNone(cmd_asteroid._unpack_permanent_number(""))
        self.assertIsNone(cmd_asteroid._unpack_permanent_number("J013S"))  # satellite


class TestParseMpcorbLine(unittest.TestCase):
    def test_numbered_asteroids(self):
        for desig, expected in [
            ("00001", 1),
            ("00433", 433),
            ("10000", 10000),
            ("A0001", 100001),
            ("~0000", 620000),
        ]:
            parsed = cmd_asteroid._parse_mpcorb_line(_mpcorb_line(desig))
            self.assertIsNotNone(parsed, desig)
            self.assertEqual(parsed["number"], expected, desig)
            self.assertEqual(parsed["designation"], desig.strip())
            self.assertAlmostEqual(parsed["semimajor_axis"], 2.76, places=2)

    def test_provisional_has_null_number(self):
        parsed = cmd_asteroid._parse_mpcorb_line(_mpcorb_line("K25A00A"))
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed["number"])
        self.assertEqual(parsed["designation"], "K25A00A")
        self.assertIsNone(parsed["name"])

    def test_extracts_proper_name_from_readable_designation(self):
        parsed = cmd_asteroid._parse_mpcorb_line(
            _mpcorb_line("00001", readable="     (1) Ceres              ")
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["number"], 1)
        self.assertEqual(parsed["name"], "Ceres")

        parsed = cmd_asteroid._parse_mpcorb_line(
            _mpcorb_line("00433", readable="   (433) Eros               ")
        )
        self.assertEqual(parsed["name"], "Eros")

        # Provisional readable designation has no proper name
        parsed = cmd_asteroid._parse_mpcorb_line(
            _mpcorb_line("K25A00A", readable="           2025 AA           ")
        )
        self.assertIsNone(parsed["name"])

    def test_short_or_header_line_rejected(self):
        self.assertIsNone(cmd_asteroid._parse_mpcorb_line("too short"))
        # Separator rows in MPCORB start with a run of dashes in the designation field
        self.assertIsNone(cmd_asteroid._parse_mpcorb_line(_mpcorb_line("--------")))


class TestApparentMagnitude(unittest.TestCase):
    def test_opposition_like_geometry(self):
        # At r=delta=1 AU and phase≈0, mag ≈ H
        mag = cmd_asteroid._apparent_magnitude(10.0, 0.15, 1.0, 1.0, 0.0)
        self.assertAlmostEqual(mag, 10.0, places=2)

    def test_farther_is_fainter(self):
        near = cmd_asteroid._apparent_magnitude(10.0, 0.15, 1.0, 1.0, 10.0)
        far = cmd_asteroid._apparent_magnitude(10.0, 0.15, 2.0, 2.0, 10.0)
        self.assertGreater(far, near)


class TestVisibilityCurve(unittest.TestCase):
    def test_curve_returns_samples_and_flags(self):
        # Ceres-like elements (approximate); epoch packed K25A2
        # Tuple shape: number, designation, name, epoch, M, peri, node, i, e, n, a, H, G
        row = (
            1, "00001", "Ceres", "K25A2",
            10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77,
            3.34, 0.12,
        )
        location = EarthLocation(lat=52.2 * u.deg, lon=21.0 * u.deg, height=100 * u.m)
        result = cmd_asteroid.compute_asteroid_visibility_curve(
            row, location, "2026-06-15", step_minutes=30,
        )
        self.assertIn("night_start", result)
        self.assertIn("night_end", result)
        self.assertLess(result["night_start"], result["night_end"])
        self.assertGreater(len(result["samples"]), 1)
        sample = result["samples"][0]
        self.assertIn("altitude_deg", sample)
        self.assertIn("azimuth_deg", sample)
        self.assertIn("apparent_magnitude", sample)
        self.assertIsInstance(result["visible"], bool)
        self.assertTrue(result["has_magnitude_estimate"])
        self.assertIsNotNone(result["apparent_magnitude_at_max"])

    def test_missing_h_skips_magnitude(self):
        row = (
            1, "00001", None, "K25A2",
            10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77,
            None, 0.15,
        )
        location = EarthLocation(lat=52.2 * u.deg, lon=21.0 * u.deg, height=100 * u.m)
        result = cmd_asteroid.compute_asteroid_visibility_curve(
            row, location, "2026-06-15", step_minutes=60,
        )
        self.assertFalse(result["has_magnitude_estimate"])
        self.assertIsNone(result["apparent_magnitude_at_max"])
        self.assertTrue(all(s["apparent_magnitude"] is None for s in result["samples"]))


class TestIersConfigLazy(unittest.TestCase):
    def test_import_does_not_require_prior_iers_config(self):
        # Visibility entry points call _configure_iers_for_planning(); the
        # helper is idempotent and safe to call again.
        cmd_asteroid._configure_iers_for_planning()
        cmd_asteroid._configure_iers_for_planning()
        self.assertIsNone(cmd_asteroid.iers.conf.auto_max_age)


if __name__ == "__main__":
    unittest.main()
