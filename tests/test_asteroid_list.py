"""Tests for `hevelius asteroid list`."""

import io
import os
import unittest
from argparse import Namespace
from contextlib import redirect_stdout

from tests.dbtest import use_repository
from hevelius import db, cmd_asteroid


class TestAsteroidsList(unittest.TestCase):
    def _insert(self, cnx):
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, name, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (1, '00001', 'Ceres', 'K25A2', 10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77, 3.34, 0.12),
            (2, '00002', 'Pallas', 'K25A2', 20.1, 310.0, 173.1, 34.8, 0.229, 0.213, 2.77, 4.13, 0.11),
            (4, '00004', 'Vesta', 'K25A2', 40.0, 150.0, 103.8, 7.1, 0.089, 0.271, 2.36, 3.20, 0.32),
            (NULL, 'K25A00A', NULL, 'K25A2', 55.2, 120.0, 200.0, 5.1, 0.15, 0.30, 2.10, 18.5, 0.15)
        """)

    def _args(self, **kwargs):
        defaults = dict(
            limit=100, offset=0, sort_by='number', sort_order='asc',
            name=None, designation=None, number=None,
            numbered=None, unnumbered=False,
            mag_min=None, mag_max=None, tags=None, tags_mode='any',
            no_color=True,
        )
        defaults.update(kwargs)
        return Namespace(**defaults)

    @use_repository
    def test_list_defaults_and_filters(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        self._insert(cnx)
        cnx.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_list(self._args())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('showing 1–4 of 4', out)
        self.assertIn('Ceres', out)
        self.assertIn('Pallas', out)
        # Default sort by number ascending: Ceres before Vesta; provisional last
        self.assertLess(out.index('Ceres'), out.index('Vesta'))
        self.assertLess(out.index('Vesta'), out.index('K25A00A'))

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_list(self._args(name='ves', limit=10))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('Vesta', out)
        self.assertNotIn('Ceres', out)
        self.assertIn('of 1', out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_list(self._args(numbered=True))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('of 3', out)
        self.assertNotIn('K25A00A', out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_asteroid.asteroids_list(
                self._args(sort_by='absolute_magnitude', sort_order='desc', limit=2)
            )
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('showing 1–2 of 4', out)
        self.assertIn('more', out)

        os.environ.pop('HEVELIUS_DB_NAME')
