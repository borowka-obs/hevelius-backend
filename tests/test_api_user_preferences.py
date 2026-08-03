import json
import os
import unittest

from flask_jwt_extended import create_access_token

from tests.dbtest import use_repository
from hevelius import db
from hevelius.api import app


class TestUserPreferences(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

        with app.app_context():
            self.test_token = create_access_token(
                identity=1,
                additional_claims={'permissions': 1, 'username': 'user1'},
            )
            self.headers = {
                'Authorization': f'Bearer {self.test_token}',
                'Content-Type': 'application/json',
            }

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_get_creates_default_row(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/users/me/preferences', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['default_exposure'], 75)
        self.assertIsNone(data['default_filter'])
        self.assertIsNone(data['default_scope'])
        self.assertEqual(data['task_binning'], 2)

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_patch_updates_preferences(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch(
            '/api/users/me/preferences',
            data=json.dumps({'default_scope': 2, 'default_exposure': 120, 'task_guiding': 0}),
            headers=self.headers,
        )
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['default_scope'], 2)
        self.assertEqual(data['default_exposure'], 120)
        self.assertEqual(data['task_guiding'], 0)

        # Persisted for subsequent reads.
        response = self.app.get('/api/users/me/preferences', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(data['default_scope'], 2)

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_patch_rejects_unknown_scope(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch(
            '/api/users/me/preferences',
            data=json.dumps({'default_scope': 999}),
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 400)

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_patch_rejects_null_limit_max_sun_alt(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch(
            '/api/users/me/preferences',
            data=json.dumps({'limit_max_sun_alt': None}),
            headers=self.headers,
        )

        self.assertIn(response.status_code, (400, 422))

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_patch_accepts_valid_filter(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect(config)
        db.run_query(
            cnx,
            "INSERT INTO filters (filter_id, short_name, full_name) VALUES (1, 'L', 'Luminance')",
        )
        cnx.close()

        response = self.app.patch(
            '/api/users/me/preferences',
            data=json.dumps({'default_filter': 1}),
            headers=self.headers,
        )
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['default_filter'], 1)


if __name__ == '__main__':
    unittest.main()
