import unittest
import os
import json
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository
from hevelius import db
from hevelius.api import app


class TestAsteroids(unittest.TestCase):
    def setUp(self):
        """Set up test client before each test"""
        self.app = app.test_client()
        self.app.testing = True

        # Create a test JWT token
        with app.app_context():
            self.test_token = create_access_token(
                identity=1,  # user_id=1
                additional_claims={
                    'permissions': 1,
                    'username': 'test_user'
                }
            )
            self.headers = {
                'Authorization': f'Bearer {self.test_token}',
                'Content-Type': 'application/json'
            }

    def _insert_asteroids(self, cnx):
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, name, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (1, '00001', 'Ceres', 'K25A2', 10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77, 3.34, 0.12),
            (2, '00002', 'Pallas', 'K25A2', 20.1, 310.0, 173.1, 34.8, 0.229, 0.213, 2.77, 4.13, 0.11),
            (NULL, 'K25A00A', NULL, 'K25A2', 55.2, 120.0, 200.0, 5.1, 0.15, 0.30, 2.10, 18.5, 0.15)
            RETURNING id
        """)

    @use_repository
    def test_asteroids_list(self, config):
        """Test asteroids list endpoint: basic listing, paging, sorting, filtering"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        self._insert_asteroids(cnx)
        cnx.close()

        # Basic list
        response = self.app.get('/api/asteroids', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('asteroids', data)
        self.assertIn('total', data)
        self.assertIn('page', data)
        self.assertIn('per_page', data)
        self.assertIn('pages', data)
        self.assertEqual(data['total'], 3)
        self.assertEqual(len(data['asteroids']), 3)

        # Default sort is by number ascending, with NULLs (unnumbered) last
        numbers = [a['number'] for a in data['asteroids']]
        self.assertEqual(numbers, [1, 2, None])

        # Paging
        response = self.app.get('/api/asteroids?page=1&per_page=2', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data['asteroids']), 2)
        self.assertEqual(data['pages'], 2)

        response = self.app.get('/api/asteroids?page=2&per_page=2', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data['asteroids']), 1)

        # Sorting by absolute_magnitude descending
        response = self.app.get(
            '/api/asteroids?sort_by=absolute_magnitude&sort_order=desc', headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        mags = [a['absolute_magnitude'] for a in data['asteroids']]
        self.assertEqual(mags, sorted(mags, reverse=True))

        # Filter by exact number
        response = self.app.get('/api/asteroids?number=2', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['asteroids'][0]['designation'], '00002')

        # Filter by designation (partial match)
        response = self.app.get('/api/asteroids?designation=K25A00A', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertIsNone(data['asteroids'][0]['number'])

        # Filter by proper name (partial, case-insensitive)
        response = self.app.get('/api/asteroids?name=cere', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['asteroids'][0]['name'], 'Ceres')
        self.assertEqual(data['asteroids'][0]['number'], 1)

        # Filter by numbered=true / numbered=false
        response = self.app.get('/api/asteroids?numbered=true', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)
        self.assertTrue(all(a['number'] is not None for a in data['asteroids']))

        response = self.app.get('/api/asteroids?numbered=false', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertIsNone(data['asteroids'][0]['number'])

        # Filter by magnitude range
        response = self.app.get('/api/asteroids?mag_min=4.0&mag_max=10.0', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['asteroids'][0]['designation'], '00002')

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_asteroids_list_post(self, config):
        """Test asteroids list endpoint with POST method"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        self._insert_asteroids(cnx)
        cnx.close()

        response = self.app.post(
            '/api/asteroids',
            json={'numbered': True, 'sort_by': 'number', 'sort_order': 'desc'},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)
        self.assertEqual([a['number'] for a in data['asteroids']], [2, 1])

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_asteroid_detail(self, config):
        """Test single asteroid detail endpoint"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        self._insert_asteroids(cnx)
        rows = db.run_query(cnx, "SELECT id FROM asteroids WHERE designation = '00001'")
        asteroid_id = rows[0][0]
        cnx.close()

        response = self.app.get(f'/api/asteroids/{asteroid_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertEqual(data['asteroid']['designation'], '00001')
        self.assertEqual(data['asteroid']['number'], 1)
        self.assertEqual(data['asteroid']['asteroid_id'], asteroid_id)
        self.assertEqual(data['asteroid']['tags'], [])

        # Not found
        response = self.app.get('/api/asteroids/999999', headers=self.headers)
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_unauthorized_access(self):
        """Test unauthorized access to endpoints"""
        response = self.app.get('/api/asteroids')
        self.assertEqual(response.status_code, 401)

        response = self.app.get('/api/asteroids/1')
        self.assertEqual(response.status_code, 401)

    @use_repository
    def test_invalid_parameters(self, config):
        """Test endpoints with invalid parameters"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.get('/api/asteroids?sort_by=invalid', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        response = self.app.get('/api/asteroids?sort_order=invalid', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        response = self.app.get('/api/asteroids?page=0', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        response = self.app.get('/api/asteroids?per_page=0', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        # mag_min greater than mag_max
        response = self.app.get('/api/asteroids?mag_min=10&mag_max=5', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        os.environ.pop('HEVELIUS_DB_NAME')


if __name__ == '__main__':
    unittest.main()
