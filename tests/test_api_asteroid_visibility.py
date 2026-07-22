import unittest
import os
import json
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository
from hevelius import db
from hevelius.api import app


class TestAsteroidVisibility(unittest.TestCase):
    def setUp(self):
        """Set up test client before each test"""
        self.app = app.test_client()
        self.app.testing = True

        with app.app_context():
            self.test_token = create_access_token(
                identity=1,
                additional_claims={'permissions': 1, 'username': 'test_user'}
            )
            self.headers = {
                'Authorization': f'Bearer {self.test_token}',
                'Content-Type': 'application/json'
            }

    def _insert_asteroid(self, cnx, absolute_magnitude=3.34):
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (1, '00001', 'K25A2', 10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77, %s, 0.12)
        """, (absolute_magnitude,))
        rows = db.run_query(cnx, "SELECT id FROM asteroids WHERE designation = '00001'")
        return rows[0][0]

    def _insert_scope(self, cnx, scope_id=501, lat=52.2, lon=21.0, alt=100.0, active=True):
        db.run_query(cnx, """
            INSERT INTO telescopes (scope_id, name, descr, min_dec, max_dec, focal, aperture,
                                  lon, lat, alt, sensor_id, active)
            VALUES (%s, %s, 'Test scope', -90.0, 90.0, 1000.0, 200.0, %s, %s, %s, NULL, %s)
        """, (scope_id, f'Scope {scope_id}', lon, lat, alt, active))
        return scope_id

    @use_repository
    def test_visibility_basic(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx)
        scope_id = self._insert_scope(cnx)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/{asteroid_id}/visibility?scope_id={scope_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertEqual(data['scope_id'], scope_id)
        self.assertEqual(data['scope_name'], f'Scope {scope_id}')
        self.assertIn('night_start', data)
        self.assertIn('night_end', data)
        self.assertLess(data['night_start'], data['night_end'])
        self.assertGreater(len(data['samples']), 1)
        self.assertIn('altitude_deg', data['samples'][0])
        self.assertIn('azimuth_deg', data['samples'][0])
        self.assertIsInstance(data['visible'], bool)
        self.assertTrue(data['has_magnitude_estimate'])

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_with_explicit_date(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx)
        scope_id = self._insert_scope(cnx)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/{asteroid_id}/visibility?scope_id={scope_id}&date=2026-01-15',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['night_start'].startswith('2026-01-15'))

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_without_magnitude_data(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx, absolute_magnitude=None)
        scope_id = self._insert_scope(cnx)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/{asteroid_id}/visibility?scope_id={scope_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertFalse(data['has_magnitude_estimate'])
        self.assertIsNone(data['apparent_magnitude_at_max'])
        self.assertTrue(all(s['apparent_magnitude'] is None for s in data['samples']))

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_missing_scope_id(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx)
        cnx.close()

        response = self.app.get(f'/api/asteroids/{asteroid_id}/visibility', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_asteroid_not_found(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        scope_id = self._insert_scope(cnx)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/999999/visibility?scope_id={scope_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_scope_not_found(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/{asteroid_id}/visibility?scope_id=999999', headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_visibility_scope_without_location(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_id = self._insert_asteroid(cnx)
        scope_id = self._insert_scope(cnx, lat=None, lon=None)
        cnx.close()

        response = self.app.get(
            f'/api/asteroids/{asteroid_id}/visibility?scope_id={scope_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_unauthorized_access(self):
        response = self.app.get('/api/asteroids/1/visibility?scope_id=1')
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
