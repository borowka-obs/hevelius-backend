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
