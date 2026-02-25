import unittest
import os
import json
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository
from hevelius import db
from heveliusbackend.app import app


class TestCatalogs(unittest.TestCase):
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
    def test_catalog_search(self, config):
        """Test catalog search endpoint"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create test catalogs and objects
        cnx = db.connect()

        # Insert test catalogs
        db.run_query(cnx, """
            INSERT INTO catalogs (name, shortname, filename, descr, url, version)
            VALUES
            ('New General Catalogue', 'ngc', 'ngc.dat', 'A catalogue of deep sky objects', 'http://example.com/ngc', '1.0'),
            ('Messier Catalogue', 'm', 'm.dat', 'A catalogue of bright deep sky objects', 'http://example.com/m', '1.0')
            RETURNING shortname""")

        # Insert test objects
        db.run_query(cnx, """
            INSERT INTO objects (name, ra, decl, descr, type, catalog)
            VALUES
            ('NGC7000', 314.75, 44.37, 'North America Nebula', 'EN', 'ngc'),
            ('NGC7001', 315.12, 44.45, 'Spiral Galaxy', 'G', 'ngc'),
            ('M31', 10.68, 41.27, 'Andromeda Galaxy', 'G', 'm')
            RETURNING object_id""")
        cnx.close()

        # Test basic search
        response = self.app.get('/api/catalogs/search?query=ngc7', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('objects', data)
        self.assertTrue(len(data['objects']) > 0)

        # Test search with limit
        response = self.app.get('/api/catalogs/search?query=ngc&limit=1', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(len(data['objects']) <= 1)

        # Test search with no results
        response = self.app.get('/api/catalogs/search?query=nonexistent', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data['objects']), 0)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_catalog_list(self, config):
        """Test catalog list endpoint"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create test catalogs and objects
        cnx = db.connect()

        # Insert test catalogs
        db.run_query(cnx, """
            INSERT INTO catalogs (name, shortname, filename, descr, url, version)
            VALUES
            ('New General Catalogue', 'ngc', 'ngc.dat', 'A catalogue of deep sky objects', 'http://example.com/ngc', '1.0'),
            ('Messier Catalogue', 'm', 'm.dat', 'A catalogue of bright deep sky objects', 'http://example.com/m', '1.0')
            RETURNING shortname""")

        # Insert test objects
        db.run_query(cnx, """
            INSERT INTO objects (name, ra, decl, descr, type, catalog)
            VALUES
            ('NGC7000', 314.75, 44.37, 'North America Nebula', 'EN', 'ngc'),
            ('NGC7001', 315.12, 44.45, 'Spiral Galaxy', 'G', 'ngc'),
            ('M31', 10.68, 41.27, 'Andromeda Galaxy', 'G', 'm')
            RETURNING object_id""")
        cnx.close()

        # Test basic list
        response = self.app.get('/api/catalogs/list', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('objects', data)
        self.assertIn('total', data)
        self.assertIn('page', data)
        self.assertIn('per_page', data)
        self.assertIn('pages', data)

        # Test pagination
        response = self.app.get('/api/catalogs/list?page=1&per_page=2', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(len(data['objects']) <= 2)

        # Test sorting
        response = self.app.get('/api/catalogs/list?sort_by=name&sort_order=asc', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        objects = data['objects']
        self.assertEqual(objects, sorted(objects, key=lambda x: x['name']))

        # Test filtering by catalog
        response = self.app.get('/api/catalogs/list?catalog=ngc', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(all(obj['catalog'] == 'ngc' for obj in data['objects']))

        # Test filtering by name
        response = self.app.get('/api/catalogs/list?name=7000', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(all('7000' in obj['name'].lower() for obj in data['objects']))

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_catalog_list_filter_by_constellation(self, config):
        """Test catalog list filtering by constellation (const)"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        db.run_query(cnx, """
            INSERT INTO catalogs (name, shortname, filename, descr, url, version)
            VALUES
            ('New General Catalogue', 'ngc', 'ngc.dat', 'NGC', 'http://example.com/ngc', '1.0'),
            ('Messier Catalogue', 'm', 'm.dat', 'M', 'http://example.com/m', '1.0')
            RETURNING shortname""")
        db.run_query(cnx, """
            INSERT INTO objects (name, ra, decl, descr, type, catalog, const)
            VALUES
            ('NGC6523', 270.97, -24.38, 'Lagoon Nebula', 'EN', 'ngc', 'Sgr'),
            ('NGC6720', 283.40, 33.03, 'Ring Nebula', 'PN', 'ngc', 'Lyr'),
            ('M8', 270.97, -24.38, 'Lagoon', 'EN', 'm', 'Sgr')
            RETURNING object_id""")
        cnx.close()

        # Filter by constellation Sgr: expect NGC6523 and M8
        response = self.app.get('/api/catalogs/list?constellation=Sgr', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)
        self.assertTrue(all(obj['const'] == 'Sgr' for obj in data['objects']))
        names = {obj['name'] for obj in data['objects']}
        self.assertEqual(names, {'NGC6523', 'M8'})

        # Filter by constellation Lyr: expect only NGC6720
        response = self.app.get('/api/catalogs/list?constellation=Lyr', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['objects'][0]['name'], 'NGC6720')
        self.assertEqual(data['objects'][0]['const'], 'Lyr')

        # Constellation filter is case-insensitive
        response = self.app.get('/api/catalogs/list?constellation=sgr', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_catalog_list_filter_catalog_case_insensitive(self, config):
        """Test that catalog filter matches case-insensitively (e.g. catalog=NGC matches 'ngc')"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        cnx = db.connect()
        db.run_query(cnx, """
            INSERT INTO catalogs (name, shortname, filename, descr, url, version)
            VALUES
            ('New General Catalogue', 'ngc', 'ngc.dat', 'NGC', 'http://example.com/ngc', '1.0'),
            ('Messier Catalogue', 'm', 'm.dat', 'M', 'http://example.com/m', '1.0')
            RETURNING shortname""")
        db.run_query(cnx, """
            INSERT INTO objects (name, ra, decl, descr, type, catalog)
            VALUES
            ('NGC7000', 314.75, 44.37, 'North America Nebula', 'EN', 'ngc'),
            ('NGC7001', 315.12, 44.45, 'Spiral Galaxy', 'G', 'ngc'),
            ('M31', 10.68, 41.27, 'Andromeda Galaxy', 'G', 'm')
            RETURNING object_id""")
        cnx.close()

        # Query with uppercase catalog=NGC: should return both ngc objects (ILIKE)
        response = self.app.get('/api/catalogs/list?catalog=NGC', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 2)
        self.assertTrue(all(obj['catalog'] == 'ngc' for obj in data['objects']))

        # Query with lowercase catalog=m: should return M31
        response = self.app.get('/api/catalogs/list?catalog=m', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['objects'][0]['name'], 'M31')

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_catalog_list_post(self, config):
        """Test catalog list endpoint with POST method"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create test catalogs and objects
        cnx = db.connect()

        # Insert test catalogs
        db.run_query(cnx, """
            INSERT INTO catalogs (name, shortname, filename, descr, url, version)
            VALUES
            ('New General Catalogue', 'ngc', 'ngc.dat', 'A catalogue of deep sky objects', 'http://example.com/ngc', '1.0'),
            ('Messier Catalogue', 'm', 'm.dat', 'A catalogue of bright deep sky objects', 'http://example.com/m', '1.0')
            RETURNING shortname""")

        # Insert test objects
        db.run_query(cnx, """
            INSERT INTO objects (name, ra, decl, descr, type, catalog)
            VALUES
            ('NGC7000', 314.75, 44.37, 'North America Nebula', 'EN', 'ngc'),
            ('NGC7001', 315.12, 44.45, 'Spiral Galaxy', 'G', 'ngc'),
            ('M31', 10.68, 41.27, 'Andromeda Galaxy', 'G', 'm')
            RETURNING object_id""")
        cnx.close()

        # Test POST with filters
        response = self.app.post('/api/catalogs/list',
                                 json={
                                   'catalog': 'ngc',
                                   'name': '7000',
                                   'sort_by': 'name',
                                   'sort_order': 'asc'
                                 },
                                 headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(all(obj['catalog'] == 'ngc' for obj in data['objects']))
        self.assertTrue(all('7000' in obj['name'].lower() for obj in data['objects']))
        objects = data['objects']
        self.assertEqual(objects, sorted(objects, key=lambda x: x['name']))

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_unauthorized_access(self):
        """Test unauthorized access to endpoints"""
        # Test search endpoint without token
        response = self.app.get('/api/catalogs/search?query=ngc7')
        self.assertEqual(response.status_code, 401)

        # Test list endpoint without token
        response = self.app.get('/api/catalogs/list')
        self.assertEqual(response.status_code, 401)

    @use_repository
    def test_invalid_parameters(self, config):
        """Test endpoints with invalid parameters"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Test invalid sort field
        response = self.app.get('/api/catalogs/list?sort_by=invalid', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        # Test invalid sort order
        response = self.app.get('/api/catalogs/list?sort_order=invalid', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        # Test invalid page number
        response = self.app.get('/api/catalogs/list?page=0', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        # Test invalid per_page value
        response = self.app.get('/api/catalogs/list?per_page=0', headers=self.headers)
        self.assertEqual(response.status_code, 422)

        os.environ.pop('HEVELIUS_DB_NAME')


if __name__ == '__main__':
    unittest.main()
