import unittest
import os
import json
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository
from hevelius import db
from hevelius.api import app


class TestAsteroidTags(unittest.TestCase):
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

    def _insert_asteroids(self, cnx):
        # Note: db.run_query()'s INSERT path only fetchone()s, so a multi-row
        # RETURNING would silently drop rows; fetch ids back with a SELECT instead.
        db.run_query(cnx, """
            INSERT INTO asteroids (
                number, designation, epoch, mean_anomaly, perihelion_arg,
                ascending_node, inclination, eccentricity, mean_motion,
                semimajor_axis, absolute_magnitude, slope_parameter
            ) VALUES
            (1, '00001', 'K25A2', 10.5, 73.6, 80.3, 10.6, 0.078, 0.214, 2.77, 3.34, 0.12),
            (2, '00002', 'K25A2', 20.1, 310.0, 173.1, 34.8, 0.229, 0.213, 2.77, 4.13, 0.11),
            (3, '00003', 'K25A2', 40.0, 150.0, 103.8, 7.1, 0.089, 0.271, 2.36, 3.20, 0.32)
        """)
        rows = db.run_query(cnx, "SELECT id FROM asteroids WHERE designation IN ('00001', '00002', '00003') ORDER BY designation")
        return [r[0] for r in rows]

    def _create_tag(self, name, description=None, color=None):
        response = self.app.post(
            '/api/asteroid-tags',
            json={'name': name, 'description': description, 'color': color},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data)['tag_id']

    @use_repository
    def test_create_list_and_get_tag(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.post(
            '/api/asteroid-tags',
            json={'name': 'neo', 'description': 'Near-Earth object', 'color': '#e53935'},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        tag_id = data['tag_id']
        self.assertEqual(data['tag']['name'], 'neo')
        self.assertEqual(data['tag']['asteroid_count'], 0)

        response = self.app.get('/api/asteroid-tags', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        tags = json.loads(response.data)['tags']
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]['tag_id'], tag_id)
        self.assertEqual(tags[0]['description'], 'Near-Earth object')

        response = self.app.get(f'/api/asteroid-tags/{tag_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertEqual(data['tag']['name'], 'neo')

        response = self.app.get('/api/asteroid-tags/999999', headers=self.headers)
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_create_duplicate_tag_name_fails(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        self._create_tag('pha')
        response = self.app.post(
            '/api/asteroid-tags', json={'name': 'pha'}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_create_tag_requires_name(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.post('/api/asteroid-tags', json={}, headers=self.headers)
        self.assertEqual(response.status_code, 422)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_edit_tag(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        tag_id = self._create_tag('amor', description='Amor family')

        response = self.app.patch(
            f'/api/asteroid-tags/{tag_id}',
            json={'description': 'Amor group asteroid', 'color': '#3949ab'},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['tag']['description'], 'Amor group asteroid')
        self.assertEqual(data['tag']['color'], '#3949ab')
        self.assertEqual(data['tag']['name'], 'amor')

        # Explicit null clears nullable fields
        response = self.app.patch(
            f'/api/asteroid-tags/{tag_id}',
            json={'description': None, 'color': None},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsNone(data['tag']['description'])
        self.assertIsNone(data['tag']['color'])
        self.assertEqual(data['tag']['name'], 'amor')

        # Renaming to a name already used by another tag fails
        self._create_tag('apollo')
        response = self.app.patch(
            f'/api/asteroid-tags/{tag_id}', json={'name': 'apollo'}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

        response = self.app.patch(
            '/api/asteroid-tags/999999', json={'name': 'x'}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_delete_tag_removes_it_from_asteroids(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_ids = self._insert_asteroids(cnx)
        cnx.close()
        tag_id = self._create_tag('fast rotator')

        self.app.post(
            f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': tag_id}, headers=self.headers
        )
        response = self.app.get(f'/api/asteroids/{asteroid_ids[0]}', headers=self.headers)
        self.assertEqual(len(json.loads(response.data)['asteroid']['tags']), 1)

        response = self.app.delete(f'/api/asteroid-tags/{tag_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)

        response = self.app.get('/api/asteroid-tags', headers=self.headers)
        self.assertEqual(json.loads(response.data)['tags'], [])

        response = self.app.get(f'/api/asteroids/{asteroid_ids[0]}', headers=self.headers)
        self.assertEqual(json.loads(response.data)['asteroid']['tags'], [])

        response = self.app.delete('/api/asteroid-tags/999999', headers=self.headers)
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_attach_and_detach_tag(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_ids = self._insert_asteroids(cnx)
        cnx.close()
        tag_id = self._create_tag('neo')

        response = self.app.post(
            f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': tag_id}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.data)['status'])

        # Attaching again is idempotent, no error, no duplicate
        response = self.app.post(
            f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': tag_id}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.data)['status'])

        response = self.app.get(f'/api/asteroids/{asteroid_ids[0]}', headers=self.headers)
        tags = json.loads(response.data)['asteroid']['tags']
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]['name'], 'neo')

        response = self.app.get('/api/asteroid-tags', headers=self.headers)
        tags_list = json.loads(response.data)['tags']
        self.assertEqual(tags_list[0]['asteroid_count'], 1)

        response = self.app.delete(
            f'/api/asteroids/{asteroid_ids[0]}/tags/{tag_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 200)

        response = self.app.get(f'/api/asteroids/{asteroid_ids[0]}', headers=self.headers)
        self.assertEqual(json.loads(response.data)['asteroid']['tags'], [])

        # Detaching a tag that isn't attached is a harmless no-op
        response = self.app.delete(
            f'/api/asteroids/{asteroid_ids[0]}/tags/{tag_id}', headers=self.headers
        )
        self.assertEqual(response.status_code, 200)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_attach_unknown_asteroid_or_tag(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_ids = self._insert_asteroids(cnx)
        cnx.close()
        tag_id = self._create_tag('neo')

        response = self.app.post(
            '/api/asteroids/999999/tags', json={'tag_id': tag_id}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

        response = self.app.post(
            f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': 999999}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_asteroids_list_includes_tags(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_ids = self._insert_asteroids(cnx)
        cnx.close()
        tag_id = self._create_tag('neo')
        self.app.post(f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': tag_id}, headers=self.headers)

        response = self.app.get('/api/asteroids', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        asteroids = {a['asteroid_id']: a for a in json.loads(response.data)['asteroids']}
        self.assertEqual(len(asteroids[asteroid_ids[0]]['tags']), 1)
        self.assertEqual(asteroids[asteroid_ids[0]]['tags'][0]['name'], 'neo')
        # Embedded tags omit asteroid_count (vocabulary endpoints include it)
        self.assertNotIn('asteroid_count', asteroids[asteroid_ids[0]]['tags'][0])
        self.assertEqual(asteroids[asteroid_ids[1]]['tags'], [])

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filter_asteroids_by_tags_any_and_all(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        asteroid_ids = self._insert_asteroids(cnx)
        cnx.close()
        neo_id = self._create_tag('neo')
        pha_id = self._create_tag('pha')

        # asteroid_ids[0]: neo only
        self.app.post(f'/api/asteroids/{asteroid_ids[0]}/tags', json={'tag_id': neo_id}, headers=self.headers)
        # asteroid_ids[1]: pha only
        self.app.post(f'/api/asteroids/{asteroid_ids[1]}/tags', json={'tag_id': pha_id}, headers=self.headers)
        # asteroid_ids[2]: both neo and pha
        self.app.post(f'/api/asteroids/{asteroid_ids[2]}/tags', json={'tag_id': neo_id}, headers=self.headers)
        self.app.post(f'/api/asteroids/{asteroid_ids[2]}/tags', json={'tag_id': pha_id}, headers=self.headers)

        # Default mode ("any"): asteroids with neo OR pha -> all three
        response = self.app.get('/api/asteroids?tags=neo,pha', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 3)

        # Filter by a single tag
        response = self.app.get('/api/asteroids?tags=neo', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)
        ids = {a['asteroid_id'] for a in data['asteroids']}
        self.assertEqual(ids, {asteroid_ids[0], asteroid_ids[2]})

        # "all" mode: must have both neo AND pha -> only asteroid_ids[2]
        response = self.app.get('/api/asteroids?tags=neo,pha&tags_mode=all', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['asteroids'][0]['asteroid_id'], asteroid_ids[2])

        # Unknown tag name matches nothing
        response = self.app.get('/api/asteroids?tags=doesnotexist', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 0)

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_unauthorized_access(self):
        response = self.app.get('/api/asteroid-tags')
        self.assertEqual(response.status_code, 401)

        response = self.app.post('/api/asteroid-tags', json={'name': 'x'})
        self.assertEqual(response.status_code, 401)

        response = self.app.post('/api/asteroids/1/tags', json={'tag_id': 1})
        self.assertEqual(response.status_code, 401)

        response = self.app.delete('/api/asteroids/1/tags/1')
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
