"""Tests for asteroid name lookup helpers and CLI show presentation."""

import io
import os
import unittest
from argparse import Namespace
from contextlib import redirect_stdout

from tests.dbtest import use_repository
from hevelius import db, cmd_asteroid


class TestAsteroidNameLookup(unittest.TestCase):
    def _insert(self, cnx):
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, name, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (1, '00001', 'Ceres', 'K25A2', 10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77, 3.34, 0.12),
            (2, '00002', 'Pallas', 'K25A2', 20.1, 310.0, 173.1, 34.8, 0.229, 0.213, 2.77, 4.13, 0.11),
            (433, '00433', 'Eros', 'K25A2', 40.0, 150.0, 103.8, 10.8, 0.223, 0.560, 1.46, 10.3, 0.46),
            (NULL, 'K25A00A', NULL, 'K25A2', 55.2, 120.0, 200.0, 5.1, 0.15, 0.30, 2.10, 18.5, 0.15)
        """)

    @use_repository
    def test_find_by_name_number_designation(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        self._insert(cnx)

        by_name = db.asteroids_find_by_query(cnx, 'ceres')
        self.assertEqual(len(by_name), 1)
        self.assertEqual(by_name[0][3], 'Ceres')

        by_number = db.asteroids_find_by_query(cnx, '433')
        self.assertEqual(len(by_number), 1)
        self.assertEqual(by_number[0][3], 'Eros')

        by_desig = db.asteroids_find_by_query(cnx, 'K25A00A')
        self.assertEqual(len(by_desig), 1)
        self.assertIsNone(by_desig[0][3])

        partial = db.asteroids_find_by_query(cnx, 'er')
        # Eros matches; Ceres does not contain 'er' as substring... wait Ceres has 'er'
        names = {r[3] for r in partial if r[3]}
        self.assertIn('Eros', names)
        self.assertIn('Ceres', names)

        cnx.close()
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_cli_show_exact_and_ambiguous(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        self._insert(cnx)
        cnx.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_show(Namespace(query='Ceres', limit=20, no_color=True))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('(1) Ceres', out)
        self.assertIn('Packed designation', out)
        self.assertIn('00001', out)
        self.assertIn('Semi-major axis', out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_show(Namespace(query='er', limit=20, no_color=True))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('Multiple matches', out)
        self.assertIn('Eros', out)
        self.assertIn('Ceres', out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_show(Namespace(query='NoSuchRock', limit=20, no_color=True))
        self.assertEqual(rc, 1)
        self.assertIn('No asteroid matching', buf.getvalue())

        os.environ.pop('HEVELIUS_DB_NAME')


class TestExtractName(unittest.TestCase):
    def test_extract_name_from_readable(self):
        self.assertEqual(
            cmd_asteroid._extract_name_from_readable('     (1) Ceres              '),
            'Ceres',
        )
        self.assertEqual(
            cmd_asteroid._extract_name_from_readable('(433) Eros'),
            'Eros',
        )
        self.assertIsNone(cmd_asteroid._extract_name_from_readable('1960 SB1'))
        self.assertIsNone(cmd_asteroid._extract_name_from_readable('(123456)'))
        self.assertIsNone(cmd_asteroid._extract_name_from_readable(''))


class TestAltitudeChart(unittest.TestCase):
    def test_render_altitude_chart_has_horizon_and_times(self):
        samples = [
            {"time": "2026-07-22 20:00:00.000", "altitude_deg": -10.0,
             "azimuth_deg": 90.0, "apparent_magnitude": 8.0, "moon_up": False},
            {"time": "2026-07-22 22:00:00.000", "altitude_deg": 20.0,
             "azimuth_deg": 120.0, "apparent_magnitude": 7.5, "moon_up": True},
            {"time": "2026-07-23 00:00:00.000", "altitude_deg": 45.0,
             "azimuth_deg": 180.0, "apparent_magnitude": 7.0, "moon_up": True},
            {"time": "2026-07-23 02:00:00.000", "altitude_deg": 15.0,
             "azimuth_deg": 240.0, "apparent_magnitude": 7.4, "moon_up": False},
            {"time": "2026-07-23 04:00:00.000", "altitude_deg": -5.0,
             "azimuth_deg": 270.0, "apparent_magnitude": 8.1, "moon_up": False},
        ]
        lines = cmd_asteroid.render_altitude_chart(samples, width=40, height=10, color=False)
        joined = "\n".join(lines)
        self.assertIn("horizon", joined)
        self.assertIn("●", joined)
        self.assertIn("20:00", joined)
        self.assertIn("04:00", joined)

        colored = "\n".join(
            cmd_asteroid.render_altitude_chart(samples, width=40, height=10, color=True)
        )
        self.assertIn("\033[33m", colored)  # yellow for moon-up columns
        self.assertIn("asteroid + moon up", colored)


class TestNightWindow(unittest.TestCase):
    def test_summer_night_is_evening_to_morning_not_daytime(self):
        from astropy.coordinates import EarthLocation
        from astropy.time import Time
        from astropy import units as u

        loc = EarthLocation(lat=52.2 * u.deg, lon=21.0 * u.deg, height=100 * u.m)
        start, end = cmd_asteroid._get_night_times(loc, Time("2026-07-22 00:00:00"))
        self.assertLess(start, end)
        # Must cross midnight and start in the evening (not the old 06:00–18:00 fallback)
        self.assertNotEqual(start.iso[:10], end.iso[:10])
        self.assertGreaterEqual(int(start.iso[11:13]), 15)
        self.assertLess(int(end.iso[11:13]), 8)


class TestTelescopeResolveAndShowVisibility(unittest.TestCase):
    def _insert_asteroid(self, cnx):
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, name, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (4, '00004', 'Vesta', 'K25A2', 10.5, 73.6, 80.3, 7.1, 0.089, 0.271, 2.36, 3.20, 0.32)
        """)

    def _insert_scope(self, cnx, scope_id=3, name='hakos-e180', lat=-23.2, lon=16.3, alt=1800.0):
        db.run_query(cnx, """
            INSERT INTO telescopes (scope_id, name, descr, min_dec, max_dec, focal, aperture,
                                  lon, lat, alt, sensor_id, active)
            VALUES (%s, %s, 'Test', -90.0, 90.0, 1800.0, 180.0, %s, %s, %s, NULL, true)
        """, (scope_id, name, lon, lat, alt))

    @use_repository
    def test_telescope_resolve_by_id_and_name(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        self._insert_scope(cnx)

        by_id = db.telescope_resolve(cnx, scope_id=3)
        self.assertEqual(by_id[0], 3)
        self.assertEqual(by_id[1], 'hakos-e180')

        by_name = db.telescope_resolve(cnx, name='hakos-e180')
        self.assertEqual(by_name[0], 3)

        by_partial = db.telescope_resolve(cnx, name='hakos')
        self.assertEqual(by_partial[0], 3)

        with self.assertRaises(ValueError):
            db.telescope_resolve(cnx, scope_id=999)

        with self.assertRaises(ValueError):
            db.telescope_resolve(cnx, name='missing-scope')

        cnx.close()
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_cli_show_with_telescope_prints_chart(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        self._insert_asteroid(cnx)
        self._insert_scope(cnx)
        cnx.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_show(Namespace(
                query='Vesta',
                limit=20,
                no_color=True,
                telescope_id=3,
                telescope=None,
                date='2026-07-22',
                step_minutes=30,
            ))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('(4) Vesta', out)
        self.assertIn('Visibility', out)
        self.assertIn('hakos-e180', out)
        self.assertIn('horizon', out)
        self.assertIn('Max altitude', out)
        self.assertIn('Sunset', out)
        self.assertIn('Sunrise', out)
        self.assertIn('Moonrise', out)
        self.assertIn('Moonset', out)
        # Must not be the old daytime fallback window
        self.assertNotIn('06:00 → 18:00', out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_show(Namespace(
                query='Vesta',
                limit=20,
                no_color=True,
                telescope_id=None,
                telescope='hakos-e180',
                date='2026-07-22',
                step_minutes=60,
            ))
        self.assertEqual(rc, 0)
        self.assertIn('Visibility', buf.getvalue())

        os.environ.pop('HEVELIUS_DB_NAME')
