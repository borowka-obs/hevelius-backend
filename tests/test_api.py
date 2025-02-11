import unittest
import os
from app import app
import json
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository


class TestTaskAdd(unittest.TestCase):
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

    @use_repository
    def test_task_add_success(self, config):
        """Test successful task addition"""
        test_task = {
            "user_id": 1,  # This should match the token's identity
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,  # ~00h 42m for M31
            "decl": 41.27,  # ~41° 16' for M31
            "exposure": 300.0,
            "filter": "L",
            "binning": 1,
            "guiding": True,
            "dither": False,
            "solve": True,
            "calibrate": True
        }

        print(f"#### test_task_add_success() config={config}")
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        os.environ.pop('HEVELIUS_DB_NAME')

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIsInstance(data['task_id'], int)
        self.assertIn('Task', data['msg'])
        self.assertIn('created successfully', data['msg'])

    def test_task_add_missing_required(self):
        """Test task addition with missing required fields"""
        test_task = {
            "object": "M31",
            "exposure": 300.0
        }

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 422)  # Unprocessable Entity
        self.assertIn('errors', data)

    def test_task_add_invalid_ra(self):
        """Test task addition with invalid RA value"""
        test_task = {
            "user_id": 1,
            "scope_id": 1,
            "object": "M31",
            "ra": 25.0,  # Invalid: RA must be 0-24
            "decl": 41.27,
            "exposure": 300.0
        }

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 422)  # Unprocessable Entity
        self.assertIn('errors', data)

    def test_task_add_invalid_dec(self):
        """Test task addition with invalid declination value"""
        test_task = {
            "user_id": 1,
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,
            "decl": 91.0,  # Invalid: Dec must be -90 to +90
            "exposure": 300.0
        }

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 422)  # Unprocessable Entity
        self.assertIn('errors', data)

    def test_task_add_unauthorized(self):
        """Test task addition with mismatched user_id"""
        test_task = {
            "user_id": 2,  # Different from token's identity (1)
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "exposure": 300.0
        }

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)  # API returns 200 with error message
        self.assertFalse(data['status'])
        self.assertEqual(data['msg'], 'Unauthorized: token user_id does not match request user_id')


if __name__ == '__main__':
    unittest.main()
