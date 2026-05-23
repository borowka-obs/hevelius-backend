# This is a workaround to suppress the specific marshmallow warning
# that happens when running the tests. This warning is not relevant
# and it's caused by one of our dependencies.

import unittest
import os
import warnings
import json
import time
from datetime import datetime
from flask_jwt_extended import create_access_token
from tests.dbtest import use_repository
from marshmallow import warnings as marshmallow_warnings
from hevelius import db

# Suppress the specific marshmallow warning
warnings.filterwarnings("ignore", category=marshmallow_warnings.RemovedInMarshmallow4Warning)

from heveliusbackend.app import app  # noqa: E402


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
            "scope_id": 1,  # Required telescope ID
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

        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIsInstance(data['task_id'], int)
        self.assertIn('Task', data['msg'])
        self.assertIn('created successfully', data['msg'])

        # Verify the task was actually added to the database
        task_id = data['task_id']
        cnx = db.connect()
        query = """SELECT task_id, user_id, scope_id, object, ra, decl, exposure,
                         filter, binning, guiding, dither, solve, calibrate, state
                  FROM tasks WHERE task_id = %s"""
        result = db.run_query(cnx, query, (task_id,))
        cnx.close()

        self.assertIsNotNone(result, "Task not found in database")
        self.assertEqual(len(result), 1, "Expected exactly one task")

        task = result[0]
        # Verify all fields match what we sent
        self.assertEqual(task[0], task_id)  # task_id
        self.assertEqual(task[1], test_task['user_id'])  # user_id
        self.assertEqual(task[2], test_task['scope_id'])  # scope_id
        self.assertEqual(task[3], test_task['object'])  # object
        self.assertEqual(float(task[4]), test_task['ra'])  # ra
        self.assertEqual(float(task[5]), test_task['decl'])  # decl
        self.assertEqual(float(task[6]), test_task['exposure'])  # exposure
        self.assertEqual(task[7], test_task['filter'])  # filter
        self.assertEqual(task[8], test_task['binning'])  # binning
        self.assertEqual(bool(task[9]), test_task['guiding'])  # guiding
        self.assertEqual(bool(task[10]), test_task['dither'])  # dither
        self.assertEqual(bool(task[11]), test_task['solve'])  # solve
        self.assertEqual(bool(task[12]), test_task['calibrate'])  # calibrate
        self.assertEqual(task[13], 1)  # state should be 1 for new tasks

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_task_add_missing_required(self):
        """Test task addition with missing required fields"""
        test_task = {
            "object": "M31",
            "exposure": 300.0
            # Missing required fields: user_id and scope_id
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

    def test_task_add_done_requires_imagename(self):
        """State=6 requires imagename on add."""
        test_task = {
            "user_id": 1,
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "state": 6
        }
        response = self.app.post('/api/task-add', data=json.dumps(test_task), headers=self.headers)
        self.assertEqual(response.status_code, 422)

    @use_repository
    def test_task_add_accepts_project_filter_aliases(self, config):
        """task-add accepts project_id/filter_id aliases and infers scope_id from project."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        db.run_query(cnx, "INSERT INTO filters (filter_id, short_name, full_name, active) VALUES (901, 'FX', 'Filter X', true)")
        db.run_query(cnx, "INSERT INTO projects (project_id, name, scope_id, active) VALUES (901, 'Project X', 1, true)")
        cnx.close()

        test_task = {
            "user_id": 1,
            "project_id": 901,
            "filter_id": 901,
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "state": 6,
            "imagename": "m31.fits"
        }
        response = self.app.post('/api/task-add', data=json.dumps(test_task), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        task_id = data['task_id']

        cnx = db.connect()
        row = db.run_query(cnx, "SELECT scope_id, filter, imagename FROM tasks WHERE task_id = %s", (task_id,))[0]
        links = db.run_query(cnx, "SELECT project_id FROM task_projects WHERE task_id = %s", (task_id,))
        cnx.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "FX")
        self.assertEqual(row[2], "m31.fits")
        self.assertEqual([r[0] for r in links], [901])
        os.environ.pop('HEVELIUS_DB_NAME')


class TestVersion(unittest.TestCase):
    def setUp(self):
        """Set up test client before each test"""
        self.app = app.test_client()
        self.app.testing = True

    def test_version_endpoint(self):
        """Test version endpoint returns correct version"""
        from hevelius.version import VERSION

        response = self.app.get('/api/version')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertIn('version', data)
        self.assertEqual(data['version'], VERSION)


class TestTaskGet(unittest.TestCase):
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
    def test_task_get_success(self, config):
        """Test successful task retrieval"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create a task
        test_task = {
            "user_id": 1,
            "scope_id": 1,  # Required telescope ID
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "exposure": 300.0,
            "filter": "L",
            "binning": 1,
            "guiding": True,
            "dither": False,
            "solve": True,
            "calibrate": True
        }

        # Add the task
        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)

        data = json.loads(response.data)
        task_id = data['task_id']

        # Now try to get the task
        response = self.app.get(f'/api/task-get?task_id={task_id}',
                                headers=self.headers)

        os.environ.pop('HEVELIUS_DB_NAME')

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIsNotNone(data['task'])
        self.assertEqual(data['task']['object'], 'M31')
        self.assertEqual(data['task']['ra'], 0.712)
        self.assertEqual(data['task']['decl'], 41.27)
        self.assertTrue(data['task']['scope_id'])
        self.assertTrue(test_task['scope_id'])
        self.assertEqual(data['task']['scope_id'], test_task['scope_id'])

    @use_repository
    def test_task_get_not_found(self, config):
        """Test task retrieval with non-existent task ID"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.get('/api/task-get?task_id=999999',
                                headers=self.headers)

        os.environ.pop('HEVELIUS_DB_NAME')

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('not found', data['msg'].lower())
        self.assertIsNone(data['task'])

    def test_task_get_no_auth(self):
        """Test task retrieval without authentication"""
        response = self.app.get('/api/task-get?task_id=1')
        self.assertEqual(response.status_code, 401)  # Unauthorized

    def test_task_get_missing_id(self):
        """Test task retrieval without task_id parameter"""
        response = self.app.get('/api/task-get',
                                headers=self.headers)
        self.assertEqual(response.status_code, 422)  # Unprocessable Entity


class TestTaskUpdate(unittest.TestCase):
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
    def test_task_update_success(self, config):
        """Test successful task update"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create a task
        test_task = {
            "user_id": 1,
            "scope_id": 1,  # Required telescope ID
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "exposure": 300.0,
            "filter": "L",
            "binning": 1,
            "guiding": True,
            "dither": False,
            "solve": True,
            "calibrate": True
        }

        # Add the task
        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)
        data = json.loads(response.data)
        task_id = data['task_id']

        # Update the task
        update_data = {
            "task_id": task_id,
            "scope_id": 2,  # Test updating scope_id
            "object": "M33",
            "exposure": 600.0
        }

        response = self.app.post('/api/task-update',
                                 data=json.dumps(update_data),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIn('updated successfully', data['msg'])

        # Verify the update
        response = self.app.get(f'/api/task-get?task_id={task_id}',
                                headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(data['task']['object'], 'M33')
        self.assertEqual(data['task']['exposure'], 600.0)
        # Original fields should remain unchanged
        self.assertEqual(data['task']['ra'], 0.712)
        self.assertEqual(data['task']['decl'], 41.27)
        self.assertEqual(data['task']['scope_id'], 2)  # Verify scope_id was updated

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_task_update_not_found(self, config):
        """Test updating non-existent task"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        update_data = {
            "task_id": 999999,
            "object": "M33"
        }

        response = self.app.post('/api/task-update',
                                 data=json.dumps(update_data),
                                 headers=self.headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('not found', data['msg'].lower())

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_task_update_no_auth(self):
        """Test task update without authentication"""
        update_data = {
            "task_id": 1,
            "object": "M33"
        }

        # Send request without headers (no authentication)
        response = self.app.post('/api/task-update',
                                 data=json.dumps(update_data))
        self.assertEqual(response.status_code, 401)  # Unauthorized

    def test_task_update_missing_task_id(self):
        """Test task update without task_id"""
        update_data = {
            "object": "M33"
        }

        response = self.app.post('/api/task-update',
                                 data=json.dumps(update_data),
                                 headers=self.headers)
        self.assertEqual(response.status_code, 422)  # Unprocessable Entity

    @use_repository
    def test_task_update_unauthorized_user(self, config):
        """Test updating task owned by different user"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create a task as user 1
        test_task = {
            "user_id": 1,
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27
        }

        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)
        task_id = json.loads(response.data)['task_id']

        # Create token for different user
        with app.app_context():
            other_token = create_access_token(
                identity=2,  # Different user_id
                additional_claims={
                    'permissions': 1,
                    'username': 'other_user'
                }
            )
            other_headers = {
                'Authorization': f'Bearer {other_token}',
                'Content-Type': 'application/json'
            }

        # Try to update the task as different user
        update_data = {
            "task_id": task_id,
            "object": "M33"
        }

        response = self.app.post('/api/task-update',
                                 data=json.dumps(update_data),
                                 headers=other_headers)

        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('unauthorized', data['msg'].lower())

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_task_update_done_requires_imagename(self, config):
        """Changing state to done requires imagename if task has none."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.post('/api/task-add', data=json.dumps({
            "user_id": 1, "scope_id": 1, "object": "M31", "ra": 0.712, "decl": 41.27
        }), headers=self.headers)
        task_id = json.loads(response.data)['task_id']
        response = self.app.post('/api/task-update', data=json.dumps({
            "task_id": task_id, "state": 6
        }), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('imagename is required', data['msg'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_task_update_accepts_project_filter_aliases(self, config):
        """task-update accepts project_id/filter_id aliases and updates scope/filter/imagename."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        create_resp = self.app.post('/api/task-add', data=json.dumps({
            "user_id": 1, "scope_id": 1, "object": "M31", "ra": 0.712, "decl": 41.27
        }), headers=self.headers)
        task_id = json.loads(create_resp.data)['task_id']

        cnx = db.connect()
        db.run_query(cnx, "INSERT INTO filters (filter_id, short_name, full_name, active) VALUES (902, 'FY', 'Filter Y', true)")
        db.run_query(cnx, "INSERT INTO projects (project_id, name, scope_id, active) VALUES (902, 'Project Y', 2, true)")
        cnx.close()

        response = self.app.post('/api/task-update', data=json.dumps({
            "task_id": task_id,
            "project_id": 902,
            "filter_id": 902,
            "state": 6,
            "imagename": "done.fits"
        }), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])

        cnx = db.connect()
        row = db.run_query(cnx, "SELECT scope_id, filter, state, imagename FROM tasks WHERE task_id = %s", (task_id,))[0]
        links = db.run_query(cnx, "SELECT project_id FROM task_projects WHERE task_id = %s", (task_id,))
        cnx.close()
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], "FY")
        self.assertEqual(row[2], 6)
        self.assertEqual(row[3], "done.fits")
        self.assertEqual([r[0] for r in links], [902])
        os.environ.pop('HEVELIUS_DB_NAME')


class TestNightPlan(unittest.TestCase):
    def setUp(self):
        """Set up test client before each test"""
        self.app = app.test_client()
        app.testing = True  # Set testing flag on the actual app instance

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

    def tearDown(self):
        """Clean up after each test"""
        app.testing = False  # Reset testing flag

    @use_repository
    def test_night_plan_success(self, config):
        """Test successful night plan retrieval"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create test users
        cnx = db.connect(config)
        db.run_query(cnx, """
            INSERT INTO users (user_id, login, pass, firstname, lastname, share, phone, email, permissions)
            VALUES
            (100, 'test_user', 'test_pass', 'Test', 'User', 1.0, '123456789', 'test@test.com', 1),
            (101, 'other_user', 'test_pass', 'Other', 'User', 1.0, '987654321', 'other@test.com', 1)
            RETURNING user_id""")  # Add RETURNING clause to make it return results
        cnx.close()

        # Now create test tasks
        test_tasks = [
            {
                "user_id": 100,
                "scope_id": 1,
                "object": "M31",
                "ra": 0.712,
                "decl": 41.27,
                "exposure": 300.0,
                "state": 1  # New task
            },
            {
                "user_id": 100,
                "scope_id": 1,
                "object": "M33",
                "ra": 1.5,
                "decl": 30.0,
                "exposure": 300.0,
                "state": 1  # Should NOT be included (Template task)
            },
            {
                "user_id": 101,  # Different user
                "scope_id": 1,
                "object": "M51",
                "ra": 13.5,
                "decl": 47.0,
                "exposure": 300.0,
                "state": 1  # Should be included when not filtering by user
            },
            {
                "user_id": 100,
                "scope_id": 2,  # Different scope
                "object": "M45",
                "ra": 3.75,
                "decl": 24.1,
                "exposure": 300.0,
                "state": 1  # Should not be included due to scope_id
            }
        ]

        # Add test tasks
        task_ids = []
        for task in test_tasks:
            response = self.app.post('/api/task-add',
                                     data=json.dumps(task),
                                     headers=self.headers)
            data = json.loads(response.data)
            self.assertTrue(data['status'])
            task_ids.append(data['task_id'])

        # Test night plan without user_id filter
        response = self.app.get('/api/night-plan?scope_id=1',
                                headers=self.headers)

        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('tasks', data)
        tasks = data['tasks']

        # Should find 3 tasks (all tasks for scope_id=1)
        self.assertEqual(len(tasks), 3)
        task_objects = [task['object'] for task in tasks]
        self.assertIn('M31', task_objects)
        self.assertIn('M51', task_objects)

        # Test night plan with user_id filter
        response = self.app.get('/api/night-plan?scope_id=1&user_id=100',
                                headers=self.headers)

        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('tasks', data)
        tasks = data['tasks']

        # Should find 2 tasks (only user_id=100 tasks for scope_id=1)
        self.assertEqual(len(tasks), 2)
        task_objects = [task['object'] for task in tasks]
        self.assertIn('M31', task_objects)
        self.assertNotIn('M51', task_objects)

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_night_plan_no_auth(self):
        """Test night plan retrieval without authentication"""
        response = self.app.get('/api/night-plan?scope_id=1')
        self.assertEqual(response.status_code, 401)  # Unauthorized

    def test_night_plan_missing_scope(self):
        """Test night plan retrieval without scope_id"""
        response = self.app.get('/api/night-plan',
                                headers=self.headers)
        self.assertEqual(response.status_code, 422)  # Unprocessable Entity

    @use_repository
    def test_night_plan_with_date_filters(self, config):
        """Test night plan with date parameter and skip_before/skip_after dates"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        test_date = datetime(2024, 3, 15).date()  # Specific test date
        before_date = datetime(2024, 3, 14).date()
        after_date = datetime(2024, 3, 16).date()

        # Create test tasks with different date constraints
        test_tasks = [
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "M31",
                "ra": 0.712,
                "decl": 41.27,
                "exposure": 300.0,
                "skip_before": datetime(2024, 3, 14).isoformat(),  # Before test date
                "skip_after": datetime(2024, 3, 16).isoformat(),   # After test date
                "state": 1  # Should be included
            },
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "M33",
                "ra": 1.5,
                "decl": 30.0,
                "exposure": 300.0,
                "skip_before": datetime(2024, 3, 16).isoformat(),  # After test date
                "state": 1  # Should not be included
            },
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "M51",
                "ra": 13.5,
                "decl": 47.0,
                "exposure": 300.0,
                "skip_after": datetime(2024, 3, 14).isoformat(),   # Before test date
                "state": 1  # Should not be included
            },
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "M42",
                "ra": 5.5,
                "decl": -5.4,
                "exposure": 300.0,
                # No date constraints
                "state": 1  # Should be included
            }
        ]

        # Add test tasks
        for task in test_tasks:
            response = self.app.post('/api/task-add',
                                     data=json.dumps(task),
                                     headers=self.headers)
            self.assertTrue(json.loads(response.data)['status'])

        # Test 1: Get night plan for specific date
        response = self.app.get(
            f'/api/night-plan?scope_id=1&user_id=1&date={test_date.isoformat()}',
            headers=self.headers
        )

        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('tasks', data)
        tasks = data['tasks']

        # Should find 2 tasks (M31 which is within range and M42 which has no constraints)
        self.assertEqual(len(tasks), 2)
        task_objects = set(task['object'] for task in tasks)
        self.assertEqual(task_objects, {'M31', 'M42'})

        # Test 2: Get night plan for date before skip_before
        response = self.app.get(
            f'/api/night-plan?scope_id=1&user_id=1&date={before_date.isoformat()}',
            headers=self.headers
        )

        data = json.loads(response.data)
        tasks = data['tasks']
        task_objects = set(task['object'] for task in tasks)
        # Should only find M42 (no date constraints)
        self.assertEqual(task_objects, {'M42'})

        # Test 3: Get night plan for date after skip_after
        response = self.app.get(
            f'/api/night-plan?scope_id=1&user_id=1&date={after_date.isoformat()}',
            headers=self.headers
        )

        data = json.loads(response.data)
        tasks = data['tasks']
        task_objects = set(task['object'] for task in tasks)
        # Should only find M42 (no date constraints)
        self.assertEqual(task_objects, {'M42'})

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_night_plan_invalid_date_format(self, config):
        """Test night plan with invalid date format"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Test with invalid date format
        response = self.app.get(
            '/api/night-plan?scope_id=1&user_id=1&date=invalid-date',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 422)  # Unprocessable Entity

        os.environ.pop('HEVELIUS_DB_NAME')


class TestTasks(unittest.TestCase):
    def setUp(self):
        """Set up test client before each test"""
        self.app = app.test_client()
        app.testing = True  # Set testing flag on the actual app instance

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

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_tasks_pagination(self, config):
        """Test tasks endpoint pagination"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Create 150 test tasks
        test_tasks = []
        for i in range(150):
            task = {
                "user_id": 1,
                "scope_id": 1,
                "object": f"Test Object {i}",
                "ra": 0.712,
                "decl": 41.27,
                "exposure": 300.0,
                "state": 1
            }
            test_tasks.append(task)

        # Add all test tasks
        for task in test_tasks:
            response = self.app.post('/api/task-add',
                                     data=json.dumps(task),
                                     headers=self.headers)
            self.assertTrue(json.loads(response.data)['status'])

        # Test default pagination (page 1, 100 per page)
        response = self.app.get('/api/tasks', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data['tasks']), 100)  # Default per_page
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['per_page'], 100)
        self.assertEqual(data['total'], 150)
        self.assertEqual(data['pages'], 2)

        # Test second page
        response = self.app.get('/api/tasks?page=2', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(len(data['tasks']), 50)  # Remaining tasks
        self.assertEqual(data['page'], 2)

        # Test custom per_page
        response = self.app.get('/api/tasks?per_page=50', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(len(data['tasks']), 50)
        self.assertEqual(data['pages'], 3)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_tasks_sorting(self, config):
        """Test tasks endpoint sorting"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Create test tasks with different values
        test_tasks = [
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "A Object",
                "ra": 1.0,
                "decl": 0.0,
                "exposure": 100.0,
                "state": 1
            },
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "B Object",
                "ra": 2.0,
                "decl": 10.0,
                "exposure": 200.0,
                "state": 0
            }
        ]

        # Add test tasks
        for task in test_tasks:
            response = self.app.post('/api/task-add',
                                     data=json.dumps(task),
                                     headers=self.headers)
            self.assertTrue(json.loads(response.data)['status'])

        # Test sorting by different fields
        sort_tests = [
            ('object', 'asc', 'A Object'),
            ('object', 'desc', 'B Object'),
            ('ra', 'asc', 1.0),
            ('ra', 'desc', 2.0),
            ('exposure', 'asc', 100.0),
            ('state', 'asc', 0)
        ]

        # TODO: Sorting by state doesn't seem to work.

        for sort_by, sort_order, expected_first in sort_tests:
            response = self.app.get(
                f'/api/tasks?sort_by={sort_by}&sort_order={sort_order}',
                headers=self.headers
            )
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 200)
            self.assertTrue(len(data['tasks']) > 0)

            # Check if sorting worked
            first_task = data['tasks'][0]
            self.assertEqual(first_task[sort_by], expected_first)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_tasks_filtering(self, config):
        """Test tasks endpoint filtering"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Create test tasks with different values
        test_tasks = [
            {
                "user_id": 1,
                "scope_id": 1,
                "object": "M31",
                "ra": 0.712,
                "decl": 41.27,
                "exposure": 300.0,
                "state": 1,
                "descr": "Test description 1"
            },
            {
                "user_id": 2,
                "scope_id": 2,
                "object": "M33",
                "ra": 1.5,
                "decl": 30.0,
                "exposure": 400.0,
                "state": 0,
                "descr": "Test description 2"
            }
        ]

        # Add test tasks
        for task in test_tasks:
            response = self.app.post('/api/task-add',
                                     data=json.dumps(task),
                                     headers=self.headers)
            self.assertTrue(json.loads(response.data)['status'])

        # Test various filters
        filter_tests = [
            ('user_id=1', 1),
            ('scope_id=2', 1),
            ('object=M31', 1),
            ('ra_min=1.0&ra_max=2.0', 1),
            ('decl_min=35.0&decl_max=45.0', 1),
            ('exposure=300.0', 1),
            ('state=0', 1),
            ('descr=description', 2)  # Should match both tasks
        ]

        for query_params, expected_count in filter_tests:
            response = self.app.get(
                f'/api/tasks?{query_params}',
                headers=self.headers
            )
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(data['tasks']), expected_count)

        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_tasks_performed_date_range(self, config):
        """Test tasks endpoint filtering by performed date range"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # Create test tasks with different performed dates
        # Note: We'll need to update the performed dates directly in the database
        test_task = {
            "user_id": 1,
            "scope_id": 1,
            "object": "M31",
            "ra": 0.712,
            "decl": 41.27,
            "exposure": 300.0,
            "state": 1
        }

        # Add test task
        response = self.app.post('/api/task-add',
                                 data=json.dumps(test_task),
                                 headers=self.headers)
        task_id = json.loads(response.data)['task_id']

        # Update performed date in database
        cnx = db.connect()
        db.run_query(
            cnx,
            "UPDATE tasks SET performed = %s WHERE task_id = %s",
            (datetime(2024, 1, 1, 12, 0, 0), task_id)
        )
        cnx.close()

        # Test date range filtering
        date_range_tests = [
            # Should find the task
            ('2024-01-01T00:00:00', '2024-01-02T00:00:00', 1),
            # Should not find the task
            ('2024-01-02T00:00:00', '2024-01-03T00:00:00', 0),
            # Should find the task
            ('2023-12-31T00:00:00', '2024-01-02T00:00:00', 1)
        ]

        for after, before, expected_count in date_range_tests:
            response = self.app.get(
                f'/api/tasks?performed_after={after}&performed_before={before}',
                headers=self.headers
            )
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(data['tasks']), expected_count)

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_tasks_invalid_sort_field(self):
        """Test tasks endpoint with invalid sort field"""
        response = self.app.get(
            '/api/tasks?sort_by=invalid_field',
            headers=self.headers
        )
        self.assertEqual(response.status_code, 422)  # Unprocessable Entity

    def test_tasks_invalid_sort_order(self):
        """Test tasks endpoint with invalid sort order"""
        response = self.app.get(
            '/api/tasks?sort_order=invalid',
            headers=self.headers
        )
        self.assertEqual(response.status_code, 422)  # Unprocessable Entity

    def test_tasks_no_auth(self):
        """Test tasks endpoint without authentication"""
        response = self.app.get('/api/tasks')
        self.assertEqual(response.status_code, 401)  # Unauthorized


class TestTaskFilenameEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        app.testing = True
        with app.app_context():
            self.test_token = create_access_token(
                identity=1,
                additional_claims={"permissions": 1, "username": "test_user"},
            )
            self.headers = {
                "Authorization": f"Bearer {self.test_token}",
                "Content-Type": "application/json",
            }

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_task_find_by_filename_suffix_and_like_escaping(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.post(
            "/api/task-add",
            data=json.dumps(
                {
                    "user_id": 1,
                    "scope_id": 1,
                    "object": "M31",
                    "ra": 0.712,
                    "decl": 41.27,
                    "exposure": 300.0,
                    "state": 1,
                }
            ),
            headers=self.headers,
        )
        task_id = json.loads(response.data)["task_id"]
        cnx = db.connect()
        path = "celestron/2025/08/omega-centauri.fits"
        db.run_query(cnx, "UPDATE tasks SET imagename = %s WHERE task_id = %s", (path, task_id))
        cnx.close()
        r_weird = self.app.post(
            "/api/task-add",
            data=json.dumps(
                {
                    "user_id": 1,
                    "scope_id": 1,
                    "object": "WEIRD",
                    "ra": 1.0,
                    "decl": 1.0,
                    "exposure": 1.0,
                    "state": 1,
                }
            ),
            headers=self.headers,
        )
        weird_id = json.loads(r_weird.data)["task_id"]
        weird = "prefix/x%y_z.fits"
        cnx = db.connect()
        db.run_query(cnx, "UPDATE tasks SET imagename = %s WHERE task_id = %s", (weird, weird_id))
        cnx.close()

        r = self.app.get(
            "/api/task-find-by-filename?filename=omega-centauri.fits",
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertTrue(data["found"])
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["matches"][0]["task_id"], task_id)
        self.assertEqual(data["matches"][0]["filename"], path)

        r2 = self.app.get(
            "/api/task-find-by-filename?filename=x%y_z.fits",
            headers=self.headers,
        )
        self.assertEqual(r2.status_code, 200)
        d2 = json.loads(r2.data)
        self.assertTrue(d2["found"])
        self.assertEqual(len(d2["matches"]), 1)
        self.assertEqual(d2["matches"][0]["filename"], weird)

        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_tasks_filename_list_compact_and_paging(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.post(
            "/api/task-add",
            data=json.dumps(
                {
                    "user_id": 1,
                    "scope_id": 1,
                    "object": "M31",
                    "ra": 0.712,
                    "decl": 41.27,
                    "exposure": 300.0,
                    "state": 1,
                }
            ),
            headers=self.headers,
        )
        task_id = json.loads(response.data)["task_id"]
        cnx = db.connect()
        db.run_query(
            cnx,
            "UPDATE tasks SET imagename = %s WHERE task_id = %s",
            ("only-one.fits", task_id),
        )
        cnx.close()

        r = self.app.get(
            "/api/tasks-filename-list?page=1&per_page=10",
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertIn("rows", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["per_page"], 10)
        self.assertGreaterEqual(data["total"], 1)
        self.assertGreaterEqual(data["pages"], 1)
        pair = next((row for row in data["rows"] if row[0] == task_id), None)
        self.assertIsNotNone(pair)
        self.assertEqual(len(pair), 2)
        self.assertEqual(pair[0], task_id)
        self.assertEqual(pair[1], "only-one.fits")

        os.environ.pop("HEVELIUS_DB_NAME")

    def test_task_find_by_filename_requires_auth(self):
        r = self.app.get("/api/task-find-by-filename?filename=x.fits")
        self.assertEqual(r.status_code, 401)

    def test_tasks_filename_list_requires_auth(self):
        r = self.app.get("/api/tasks-filename-list")
        self.assertEqual(r.status_code, 401)


class TestScopes(unittest.TestCase):
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

    @use_repository(load_test_data=None)
    def test_scopes_success(self, config):
        """Test successful retrieval of telescopes and their sensors"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        # First create test sensors
        cnx = db.connect()
        db.run_query(cnx, """
            INSERT INTO sensors (sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height)
            VALUES
            (1, 'Test Sensor 1', 1024, 1024, 9.0, 9.0, 16, 9.216, 9.216),
            (2, 'Test Sensor 2', 2048, 2048, 4.5, 4.5, 16, 9.216, 9.216)
            RETURNING sensor_id""")
        cnx.close()

        # Create test telescopes
        cnx = db.connect()
        db.run_query(cnx, """
            INSERT INTO telescopes (scope_id, name, descr, min_dec, max_dec, focal, aperture,
                                  lon, lat, alt, sensor_id, active)
            VALUES
            (1, 'Test Scope 1', 'Test Description 1', -90.0, 90.0, 1000.0, 200.0,
             0.0, 0.0, 0.0, 1, true),
            (2, 'Test Scope 2', 'Test Description 2', -45.0, 45.0, 2000.0, 400.0,
             0.0, 0.0, 0.0, 2, true),
            (3, 'Test Scope 3', 'Test Description 3', -30.0, 30.0, 3000.0, 600.0,
             0.0, 0.0, 0.0, NULL, false)
            RETURNING scope_id""")
        cnx.close()

        # Get scopes
        response = self.app.get('/api/scopes', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertIn('telescopes', data)
        telescopes = data['telescopes']

        # Should find all 3 telescopes
        self.assertEqual(len(telescopes), 3)

        # Verify first telescope with sensor
        scope1 = next(t for t in telescopes if t['scope_id'] == 1)
        self.assertEqual(scope1['name'], 'Test Scope 1')
        self.assertEqual(scope1['descr'], 'Test Description 1')
        self.assertEqual(scope1['min_dec'], -90.0)
        self.assertEqual(scope1['max_dec'], 90.0)
        self.assertEqual(scope1['focal'], 1000.0)
        self.assertEqual(scope1['aperture'], 200.0)
        self.assertEqual(scope1['lon'], 0.0)
        self.assertEqual(scope1['lat'], 0.0)
        self.assertEqual(scope1['alt'], 0.0)
        self.assertTrue(scope1['active'])
        self.assertIsNotNone(scope1['sensor'])
        self.assertEqual(scope1['sensor']['sensor_id'], 1)
        self.assertEqual(scope1['sensor']['name'], 'Test Sensor 1')
        self.assertEqual(scope1['sensor']['resx'], 1024)
        self.assertEqual(scope1['sensor']['resy'], 1024)
        self.assertEqual(scope1['sensor']['pixel_x'], 9.0)
        self.assertEqual(scope1['sensor']['pixel_y'], 9.0)
        self.assertEqual(scope1['sensor']['bits'], 16)
        self.assertEqual(scope1['sensor']['width'], 9.216)
        self.assertEqual(scope1['sensor']['height'], 9.216)

        # Verify second telescope with different sensor
        scope2 = next(t for t in telescopes if t['scope_id'] == 2)
        self.assertEqual(scope2['name'], 'Test Scope 2')
        self.assertEqual(scope2['sensor']['sensor_id'], 2)
        self.assertEqual(scope2['sensor']['name'], 'Test Sensor 2')
        self.assertEqual(scope2['sensor']['resx'], 2048)
        self.assertEqual(scope2['sensor']['resy'], 2048)
        self.assertEqual(scope2['sensor']['pixel_x'], 4.5)
        self.assertEqual(scope2['sensor']['pixel_y'], 4.5)

        # Verify third telescope without sensor
        scope3 = next(t for t in telescopes if t['scope_id'] == 3)
        self.assertEqual(scope3['name'], 'Test Scope 3')
        self.assertIsNone(scope3['sensor'])
        self.assertFalse(scope3['active'])

        os.environ.pop('HEVELIUS_DB_NAME')

    def test_scopes_no_auth(self):
        """Test scopes endpoint without authentication"""
        response = self.app.get('/api/scopes')
        self.assertEqual(response.status_code, 401)  # Unauthorized

    @use_repository(load_test_data=None)
    def test_scopes_empty(self, config):
        """Test scopes endpoint with empty database"""
        os.environ['HEVELIUS_DB_NAME'] = config['database']

        response = self.app.get('/api/scopes', headers=self.headers)
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertIn('telescopes', data)
        self.assertEqual(len(data['telescopes']), 0)

        os.environ.pop('HEVELIUS_DB_NAME')


class TestFilters(unittest.TestCase):
    """Tests for filter CRUD: add, edit, activate, deactivate."""

    def setUp(self):
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

    @use_repository
    def test_filters_post_add(self, config):
        """Add new filter via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"short_name": "FNew", "full_name": "Luminance Red", "url": "https://example.com/lr", "active": True}
        response = self.app.post('/api/filters', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIn('filter_id', data)
        self.assertEqual(data['filter']['short_name'], 'FNew')
        self.assertEqual(data['filter']['full_name'], 'Luminance Red')
        self.assertEqual(data['filter']['url'], 'https://example.com/lr')
        self.assertTrue(data['filter']['active'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_patch_edit(self, config):
        """Edit existing filter via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        # Use filter_id 1 (SG from test data)
        body = {"full_name": "Sloan g' (edited)", "url": "https://example.com/sg"}
        response = self.app.patch('/api/filters/1', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['filter']['filter_id'], 1)
        self.assertEqual(data['filter']['short_name'], 'SG')
        self.assertEqual(data['filter']['full_name'], "Sloan g' (edited)")
        self.assertEqual(data['filter']['url'], "https://example.com/sg")
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_patch_activate(self, config):
        """Make filter active via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = db.connect()
        db.run_query(cnx, "UPDATE filters SET active = false WHERE filter_id = 2")
        cnx.close()
        response = self.app.patch('/api/filters/2', data=json.dumps({"active": True}), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertTrue(data['filter']['active'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_patch_deactivate(self, config):
        """Make filter inactive via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch('/api/filters/1', data=json.dumps({"active": False}), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertFalse(data['filter']['active'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_get_by_id(self, config):
        """Get single filter by ID."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/filters/1', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['filter']['filter_id'], 1)
        self.assertEqual(data['filter']['short_name'], 'SG')
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_post_duplicate_short_name(self, config):
        """Creating filter with existing short_name returns 400."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"short_name": "SG", "full_name": "Duplicate"}
        response = self.app.post('/api/filters', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_get_not_found(self, config):
        """GET non-existent filter returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/filters/99999', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_filters_patch_not_found(self, config):
        """PATCH non-existent filter returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch('/api/filters/99999', data=json.dumps({"active": False}), headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')


class TestSensors(unittest.TestCase):
    """Tests for sensor CRUD and list sorting."""

    def setUp(self):
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

    @use_repository
    def test_sensors_post_add(self, config):
        """Add new sensor via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {
            "name": "Test Camera",
            "resx": 1920,
            "resy": 1080,
            "pixel_x": 5.0,
            "pixel_y": 5.0,
            "vendor": "TestVendor",
            "active": True
        }
        response = self.app.post('/api/sensors', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIn('sensor_id', data)
        self.assertEqual(data['sensor']['name'], 'Test Camera')
        self.assertEqual(data['sensor']['resx'], 1920)
        self.assertEqual(data['sensor']['resy'], 1080)
        self.assertEqual(data['sensor']['vendor'], 'TestVendor')
        self.assertTrue(data['sensor']['active'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_sensors_patch_edit(self, config):
        """Edit existing sensor via API."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "QSI 583ws (edited)", "vendor": "QSI"}
        response = self.app.patch('/api/sensors/1', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['sensor']['sensor_id'], 1)
        self.assertEqual(data['sensor']['name'], "QSI 583ws (edited)")
        self.assertEqual(data['sensor']['vendor'], "QSI")
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_sensors_get_by_id(self, config):
        """Get single sensor by ID."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/sensors/1', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['sensor']['sensor_id'], 1)
        self.assertEqual(data['sensor']['name'], 'QSI 583ws')
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_sensors_list_sort(self, config):
        """List sensors with sort_by and sort_order."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/sensors?sort_by=name&sort_order=asc', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('sensors', data)
        sensors = data['sensors']
        self.assertGreaterEqual(len(sensors), 2)
        names = [s['name'] for s in sensors]
        self.assertEqual(names, sorted(names))
        response2 = self.app.get('/api/sensors?sort_by=pixel_x&sort_order=desc', headers=self.headers)
        data2 = json.loads(response2.data)
        self.assertEqual(response2.status_code, 200)
        pixels = [s['pixel_x'] for s in data2['sensors'] if s.get('pixel_x') is not None]
        self.assertEqual(pixels, sorted(pixels, reverse=True))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_sensors_get_not_found(self, config):
        """GET non-existent sensor returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/sensors/99999', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_sensors_patch_not_found(self, config):
        """PATCH non-existent sensor returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch('/api/sensors/99999', data=json.dumps({"name": "X"}), headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')


class TestTelescopeOperations(unittest.TestCase):
    """Tests for telescope CRUD: add (auto id), get, edit, set sensor, add/remove filter, list sort."""

    def setUp(self):
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

    @use_repository
    def test_telescope_post_add_auto_id(self, config):
        """Add telescope without scope_id; scope_id is auto-assigned and returned."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "New Auto Scope", "focal": 500.0, "active": True}
        response = self.app.post('/api/scopes', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIn('scope_id', data)
        self.assertIsInstance(data['scope_id'], int)
        self.assertGreater(data['scope_id'], 0)
        self.assertEqual(data['scope']['name'], 'New Auto Scope')
        self.assertEqual(data['scope']['focal'], 500.0)
        self.assertTrue(data['scope']['active'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_post_add_explicit_id(self, config):
        """Add telescope with explicit scope_id."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"scope_id": 100, "name": "Explicit ID Scope", "descr": "Test"}
        response = self.app.post('/api/scopes', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['scope_id'], 100)
        self.assertEqual(data['scope']['scope_id'], 100)
        self.assertEqual(data['scope']['name'], 'Explicit ID Scope')
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_post_duplicate_scope_id(self, config):
        """Adding telescope with existing scope_id returns error."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"scope_id": 1, "name": "Duplicate"}
        response = self.app.post('/api/scopes', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('already exists', data.get('msg', ''))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_get(self, config):
        """Get single telescope by scope_id; includes sensor and filters."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/scopes/1', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['scope']['scope_id'], 1)
        self.assertIn('name', data['scope'])
        self.assertIn('sensor', data['scope'])
        self.assertIn('filters', data['scope'])
        self.assertIsInstance(data['scope']['filters'], list)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_get_not_found(self, config):
        """GET non-existent telescope returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/scopes/99999', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('not found', data.get('msg', ''))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_patch(self, config):
        """Edit telescope via PATCH."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "Updated Scope Name", "descr": "Updated descr", "focal": 1500.0}
        response = self.app.patch('/api/scopes/1', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['scope']['name'], 'Updated Scope Name')
        self.assertEqual(data['scope']['descr'], 'Updated descr')
        self.assertEqual(data['scope']['focal'], 1500.0)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_patch_set_sensor(self, config):
        """Set sensor on telescope (sensor_id=2); then remove (sensor_id=0)."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        # Scope 3 in test data has no sensor; set sensor 2
        response = self.app.patch('/api/scopes/2', data=json.dumps({"sensor_id": 2}), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIsNotNone(data['scope']['sensor'])
        self.assertEqual(data['scope']['sensor']['sensor_id'], 2)
        # Remove sensor
        response = self.app.patch('/api/scopes/2', data=json.dumps({"sensor_id": 0}), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertIsNone(data['scope']['sensor'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_list_sort(self, config):
        """List telescopes with sort_by and sort_order."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/scopes?sort_by=name&sort_order=asc', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('telescopes', data)
        telescopes = data['telescopes']
        if len(telescopes) >= 2:
            names = [t['name'] for t in telescopes if t.get('name')]
            self.assertEqual(names, sorted(names))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_add_filter(self, config):
        """Add filter to telescope."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        # Remove filter 1 from scope 1 if present, then add it back
        self.app.delete('/api/scopes/1/filters/1', headers=self.headers)
        response = self.app.post(
            '/api/scopes/1/filters',
            data=json.dumps({"filter_id": 1}),
            headers=self.headers
        )
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        # Verify scope 1 now has filter 1
        get_resp = self.app.get('/api/scopes/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        filter_ids = [f['filter_id'] for f in get_data['scope']['filters']]
        self.assertIn(1, filter_ids)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_telescope_remove_filter(self, config):
        """Remove filter from telescope."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.delete('/api/scopes/1/filters/1', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        # Verify scope 1 no longer has filter 1
        get_resp = self.app.get('/api/scopes/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        filter_ids = [f['filter_id'] for f in get_data['scope']['filters']]
        self.assertNotIn(1, filter_ids)
        os.environ.pop('HEVELIUS_DB_NAME')


class TestProjectOperations(unittest.TestCase):
    """Tests for project and subframe CRUD: add (catalog lookup), edit, subframe add/edit/remove."""

    def setUp(self):
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

    @use_repository
    def test_projects_list_has_scope_id_and_goal_count(self, config):
        """List projects returns scope_id and subframes have goal_count."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/projects', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('projects', data)
        if data['projects']:
            p = data['projects'][0]
            self.assertIn('scope_id', p)
            for sf in p.get('subframes', []):
                self.assertIn('goal_count', sf)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_with_ra_dec(self, config):
        """Create project with name, scope_id, ra, dec."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "Test Project", "scope_id": 1, "ra": 0.5, "decl": 25.0, "description": "Desc", "regexps": "^M31$"}
        response = self.app.post('/api/projects', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(data['status'])
        self.assertIn('project_id', data)
        self.assertEqual(data['project']['name'], 'Test Project')
        self.assertEqual(data['project']['scope_id'], 1)
        self.assertEqual(data['project']['ra'], 0.5)
        self.assertEqual(data['project']['decl'], 25.0)
        self.assertEqual(data['project']['regexps'], '^M31$')
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_from_catalog(self, config):
        """Create project with name and scope_id only; ra/dec resolved from catalog (objects table)."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "C19", "scope_id": 1}
        response = self.app.post('/api/projects', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(data['status'])
        self.assertIn('project_id', data)
        self.assertEqual(data['project']['name'], 'C19')
        self.assertIsNotNone(data['project']['ra'])
        self.assertIsNotNone(data['project']['decl'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_name_not_in_catalog_fails(self, config):
        """Create project without ra/dec and name not in catalog returns 400."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "NonexistentObjectXYZ", "scope_id": 1}
        response = self.app.post('/api/projects', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('catalog', data.get('message', '').lower())
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_patch(self, config):
        """Update project via PATCH."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "Updated Z Peg", "description": "Updated desc"}
        response = self.app.patch('/api/projects/1', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertEqual(data['project']['name'], 'Updated Z Peg')
        self.assertEqual(data['project']['description'], 'Updated desc')
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add(self, config):
        """Add subframe to project."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter_id": 1, "exposure_time": 60.0, "goal_count": 20, "active": True}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(data['status'])
        self.assertIn('subframe_id', data)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add_defaults_count_to_zero(self, config):
        """Subframe count defaults to 0 when neither count nor goal_count is provided."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter_id": 1, "exposure_time": 60.0, "active": True}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        subframe_id = json.loads(response.data)['subframe_id']

        get_resp = self.app.get('/api/projects/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        sf = next(s for s in get_data['project']['subframes'] if s['id'] == subframe_id)
        self.assertEqual(sf['count'], 0)
        self.assertEqual(sf['goal_count'], 0)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_patch_count_only_does_not_touch_goal_count(self, config):
        """PATCH with only count must not modify goal_count or active."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter_id": 1, "exposure_time": 60.0, "count": 7, "goal_count": 30, "active": True}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        subframe_id = json.loads(response.data)['subframe_id']

        patch_resp = self.app.patch(
            f'/api/projects/1/subframes/{subframe_id}',
            data=json.dumps({"count": 9}),
            headers=self.headers
        )
        self.assertEqual(patch_resp.status_code, 200)

        get_resp = self.app.get('/api/projects/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        sf = next(s for s in get_data['project']['subframes'] if s['id'] == subframe_id)
        self.assertEqual(sf['count'], 9)
        self.assertEqual(sf['goal_count'], 30)
        self.assertTrue(sf['active'])
        self.assertIn('last_updated', sf)
        self.assertIsNotNone(sf['last_updated'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_patch(self, config):
        """Update subframe via PATCH."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        # Get first subframe id from project 1
        get_resp = self.app.get('/api/projects/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        subframes = get_data['project']['subframes']
        self.assertGreater(len(subframes), 0)
        subframe_id = subframes[0]['id']
        body = {"exposure_time": 99.0, "goal_count": 15}
        response = self.app.patch(f'/api/projects/1/subframes/{subframe_id}', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_delete(self, config):
        """Remove subframe from project."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        get_resp = self.app.get('/api/projects/1', headers=self.headers)
        get_data = json.loads(get_resp.data)
        subframes = get_data['project']['subframes']
        self.assertGreater(len(subframes), 0)
        subframe_id = subframes[-1]['id']
        response = self.app.delete(f'/api/projects/1/subframes/{subframe_id}', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        get_resp2 = self.app.get('/api/projects/1', headers=self.headers)
        get_data2 = json.loads(get_resp2.data)
        ids = [s['id'] for s in get_data2['project']['subframes']]
        self.assertNotIn(subframe_id, ids)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_get_one(self, config):
        """GET single project returns project with scope_id, subframes, user_ids."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/projects/1', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        p = data['project']
        self.assertIn('project_id', p)
        self.assertIn('scope_id', p)
        self.assertIn('subframes', p)
        self.assertIn('user_ids', p)
        self.assertEqual(p['project_id'], 1)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add_by_filter_short_name(self, config):
        """Add subframe using filter short name (not filter_id)."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter": "SG", "exposure_time": 120.0, "goal_count": 5}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(data['status'])
        self.assertIn('subframe_id', data)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add_both_filter_and_filter_id_fails(self, config):
        """Adding subframe with both filter and filter_id returns 400."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter": "SG", "filter_id": 1, "exposure_time": 60.0}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('only one', data.get('message', '').lower())
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add_neither_filter_nor_filter_id_fails(self, config):
        """Adding subframe with neither filter nor filter_id returns 400."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"exposure_time": 60.0}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('filter', data.get('message', '').lower())
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_add_unknown_filter_short_name_fails(self, config):
        """Adding subframe with unknown filter short name returns 400."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"filter": "NoSuchFilter", "exposure_time": 60.0}
        response = self.app.post('/api/projects/1/subframes', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('not found', data.get('message', '').lower())
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_not_found(self, config):
        """GET and PATCH non-existent project return 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.get('/api/projects/99999', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['status'])
        self.assertIn('not found', data.get('msg', '').lower())
        response = self.app.patch('/api/projects/99999', data=json.dumps({"name": "X"}), headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_not_found(self, config):
        """PATCH and DELETE non-existent subframe return 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.patch('/api/projects/1/subframes/99999', data=json.dumps({"exposure_time": 1.0}), headers=self.headers)
        self.assertEqual(response.status_code, 404)
        response = self.app.delete('/api/projects/1/subframes/99999', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_projects_list_total_integration_matches_subframes(self, config):
        """Fixture project 1 total_integration_time equals sum of exposure × count."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        r = self.app.get('/api/projects/1', headers=self.headers)
        p = json.loads(r.data)['project']
        sub_total = sum(sf['exposure_time'] * sf['count'] for sf in p['subframes'])
        self.assertAlmostEqual(p['total_integration_time'], sub_total, places=5)
        lst = self.app.get('/api/projects', headers=self.headers)
        row = next(x for x in json.loads(lst.data)['projects'] if x['project_id'] == 1)
        self.assertAlmostEqual(row['total_integration_time'], sub_total, places=5)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_subframe_change_updates_last_updated(self, config):
        """Patching a subframe bumps parent last_updated (DB trigger)."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        before = json.loads(self.app.get('/api/projects/1', headers=self.headers).data)['project']
        lu0 = before.get('last_updated')
        sf = before['subframes'][0]
        time.sleep(0.05)
        patch = self.app.patch(
            f"/api/projects/1/subframes/{sf['id']}",
            data=json.dumps({'exposure_time': float(sf['exposure_time']) + 1.0}),
            headers=self.headers,
        )
        self.assertEqual(patch.status_code, 200)
        after = json.loads(self.app.get('/api/projects/1', headers=self.headers).data)['project']
        self.assertIsNotNone(after.get('last_updated'))
        if lu0:
            self.assertNotEqual(lu0, after['last_updated'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_projects_list_sort_by_total_integration_time(self, config):
        """List API sort_by=total_integration_time orders projects by stored aggregate."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        suf = datetime.now().strftime('%H%M%S%f')
        lo = {"name": f"LoInt{suf}", "scope_id": 1, "ra": 0.2, "decl": 2.0}
        hi = {"name": f"HiInt{suf}", "scope_id": 1, "ra": 0.3, "decl": 3.0}
        id_lo = json.loads(self.app.post('/api/projects', data=json.dumps(lo), headers=self.headers).data)['project_id']
        id_hi = json.loads(self.app.post('/api/projects', data=json.dumps(hi), headers=self.headers).data)['project_id']
        self.app.post(
            f'/api/projects/{id_lo}/subframes',
            data=json.dumps({'filter_id': 1, 'exposure_time': 10.0, 'count': 1}),
            headers=self.headers,
        )
        self.app.post(
            f'/api/projects/{id_hi}/subframes',
            data=json.dumps({'filter_id': 1, 'exposure_time': 10.0, 'count': 50}),
            headers=self.headers,
        )
        asc = json.loads(
            self.app.get(
                '/api/projects?sort_by=total_integration_time&sort_order=asc',
                headers=self.headers,
            ).data
        )['projects']
        idx_lo = next(i for i, x in enumerate(asc) if x['project_id'] == id_lo)
        idx_hi = next(i for i, x in enumerate(asc) if x['project_id'] == id_hi)
        self.assertLess(idx_lo, idx_hi)
        desc = json.loads(
            self.app.get(
                '/api/projects?sort_by=total_integration_time&sort_order=desc',
                headers=self.headers,
            ).data
        )['projects']
        idx_lo_d = next(i for i, x in enumerate(desc) if x['project_id'] == id_lo)
        idx_hi_d = next(i for i, x in enumerate(desc) if x['project_id'] == id_hi)
        self.assertLess(idx_hi_d, idx_lo_d)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_and_patch_optional_dates(self, config):
        """start_date and end_date optional on create; PATCH can set and clear."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {
            'name': f'DatedProj{datetime.now().strftime("%H%M%S%f")}',
            'scope_id': 1,
            'ra': 0.4,
            'decl': 4.0,
            'start_date': '2026-01-15',
            'end_date': '2026-06-30',
        }
        cr = json.loads(self.app.post('/api/projects', data=json.dumps(body), headers=self.headers).data)
        self.assertEqual(cr['project']['start_date'], '2026-01-15')
        self.assertEqual(cr['project']['end_date'], '2026-06-30')
        pid = cr['project_id']
        clr = self.app.patch(
            f'/api/projects/{pid}',
            data=json.dumps({'start_date': None, 'end_date': None}),
            headers=self.headers,
        )
        self.assertEqual(clr.status_code, 200)
        p = json.loads(clr.data)['project']
        self.assertIsNone(p.get('start_date'))
        self.assertIsNone(p.get('end_date'))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_publications_create_patch_and_list(self, config):
        """publications stored as normalized space-separated URLs."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {
            'name': f'PubProj{datetime.now().strftime("%H%M%S%f")}',
            'scope_id': 1,
            'ra': 0.5,
            'decl': 5.0,
            'publications': '  https://www.astrobin.com/x/1   https://facebook.com/post/2  ',
        }
        cr = json.loads(self.app.post('/api/projects', data=json.dumps(body), headers=self.headers).data)
        self.assertEqual(
            cr['project']['publications'],
            'https://www.astrobin.com/x/1 https://facebook.com/post/2',
        )
        pid = cr['project_id']
        patch = json.loads(
            self.app.patch(
                f'/api/projects/{pid}',
                data=json.dumps({'publications': ''}),
                headers=self.headers,
            ).data
        )
        self.assertIsNone(patch['project'].get('publications'))
        listed = json.loads(self.app.get('/api/projects', headers=self.headers).data)
        row = next(p for p in listed['projects'] if p['project_id'] == pid)
        self.assertIsNone(row.get('publications'))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_login_refresh_returns_new_token(self, config):
        """POST /api/login/refresh extends session with a new JWT."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.post('/api/login/refresh', headers=self.headers)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['status'])
        self.assertTrue(data.get('token'))
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_delete(self, config):
        """DELETE project removes it; subsequent GET returns status=False."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"name": "ToDelete", "scope_id": 1, "ra": 0.5, "decl": 25.0}
        cr = json.loads(self.app.post('/api/projects', data=json.dumps(body), headers=self.headers).data)
        pid = cr['project_id']
        response = self.app.delete(f'/api/projects/{pid}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        get_resp = self.app.get(f'/api/projects/{pid}', headers=self.headers)
        get_data = json.loads(get_resp.data)
        self.assertFalse(get_data['status'])
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_delete_not_found(self, config):
        """DELETE non-existent project returns 404."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        response = self.app.delete('/api/projects/99999', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_similar_name_warns(self, config):
        """Creating project whose name is a substring of an existing one returns warnings."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        suf = datetime.now().strftime('%H%M%S%f')
        body1 = {"name": f"M31 Campaign {suf}", "scope_id": 1, "ra": 0.5, "decl": 25.0}
        self.app.post('/api/projects', data=json.dumps(body1), headers=self.headers)
        body2 = {"name": f"M31 Campaign {suf} extended", "scope_id": 1, "ra": 0.5, "decl": 25.0}
        response = self.app.post('/api/projects', data=json.dumps(body2), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertIn('warnings', data)
        self.assertGreater(len(data['warnings']), 0)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_create_no_similar_name_no_warnings(self, config):
        """Creating a project with a unique name returns an empty warnings list."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        suf = datetime.now().strftime('%H%M%S%f')
        body = {"name": f"UniqueXYZ{suf}", "scope_id": 1, "ra": 0.5, "decl": 25.0}
        response = self.app.post('/api/projects', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertIn('warnings', data)
        self.assertEqual(len(data['warnings']), 0)
        os.environ.pop('HEVELIUS_DB_NAME')

    @use_repository
    def test_project_edit_description(self, config):
        """PATCH can update only the description of a project."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        body = {"description": "Brand new description"}
        response = self.app.patch('/api/projects/1', data=json.dumps(body), headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['status'])
        self.assertEqual(data['project']['description'], 'Brand new description')
        os.environ.pop('HEVELIUS_DB_NAME')


class TestUsersAPI(unittest.TestCase):
    """GET /api/users/logins and GET /api/users (admin)."""

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        with app.app_context():
            self.token_no_admin = create_access_token(
                identity=1,
                additional_claims={"permissions": 0, "username": "user1"},
            )
            self.token_admin = create_access_token(
                identity=1,
                additional_claims={"permissions": 1, "username": "user1"},
            )
        self.headers_no_admin = {
            "Authorization": f"Bearer {self.token_no_admin}",
            "Content-Type": "application/json",
        }
        self.headers_admin = {
            "Authorization": f"Bearer {self.token_admin}",
            "Content-Type": "application/json",
        }

    def test_users_logins_requires_auth(self):
        response = self.app.get("/api/users/logins")
        self.assertEqual(response.status_code, 401)

    def test_users_admin_requires_auth(self):
        response = self.app.get("/api/users")
        self.assertEqual(response.status_code, 401)

    @use_repository
    def test_users_logins_ok_for_authenticated(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users/logins", headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("users", data)
        self.assertGreaterEqual(len(data["users"]), 1)
        u0 = data["users"][0]
        self.assertIn("user_id", u0)
        self.assertIn("login", u0)
        self.assertNotIn("pass_d", u0)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_full_list_forbidden_without_admin_bit(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users", headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 403)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_full_list_ok_with_admin_bit(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users", headers=self.headers_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("users", data)
        self.assertGreaterEqual(len(data["users"]), 1)
        u = next(x for x in data["users"] if x.get("user_id") == 1)
        self.assertEqual(u.get("login"), "user1")
        self.assertIn("permissions", u)
        self.assertIn("login_enabled", u)
        for forbidden in ("pass", "pass_d", "ftp_login", "ftp_pass"):
            self.assertNotIn(forbidden, u)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_ok(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users/me", headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get("user_id"), 1)
        self.assertEqual(data.get("login"), "user1")
        self.assertIn("login_enabled", data)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_audit_log_forbidden_without_admin(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users/audit-log", headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 403)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_audit_log_lists_entries(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        self.app.get("/api/users", headers=self.headers_admin)
        response = self.app.get("/api/users/audit-log?page=1&per_page=20", headers=self.headers_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("entries", data)
        self.assertIn("total", data)
        actions = [e["action"] for e in data["entries"]]
        self.assertIn("users.list_full", actions)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_password_reset_issue_and_complete(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        r = self.app.post("/api/users/1/password-reset-token", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        issue = json.loads(r.data)
        self.assertTrue(issue.get("status"))
        token = issue.get("token")
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)
        r2 = self.app.post(
            "/api/auth/password-reset",
            data=json.dumps({"token": token, "new_password": "freshpass123"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(r2.status_code, 200)
        done = json.loads(r2.data)
        self.assertTrue(done.get("status"))
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT pass_d FROM users WHERE user_id = 1", ())
        cnx.close()
        self.assertTrue(str(row[0][0]).startswith("$argon2"))
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_password_reset_token_requires_admin(self, config):
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.post("/api/users/1/password-reset-token", headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 403)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_patch_profile(self, config):
        """PATCH /api/users/me updates firstname, lastname, email, and aavso_id."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        body = {"firstname": "Alice", "lastname": "Smith", "email": "alice@example.com", "aavso_id": "AA001"}
        response = self.app.patch("/api/users/me", data=json.dumps(body), headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data["firstname"], "Alice")
        self.assertEqual(data["lastname"], "Smith")
        self.assertEqual(data["email"], "alice@example.com")
        self.assertEqual(data["aavso_id"], "AA001")
        self.assertNotIn("pass_d", data)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_patch_clear_email(self, config):
        """PATCH /api/users/me with null email clears it."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        self.app.patch("/api/users/me", data=json.dumps({"email": "set@example.com"}), headers=self.headers_no_admin)
        response = self.app.patch("/api/users/me", data=json.dumps({"email": None}), headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsNone(data.get("email"))
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_patch_requires_auth(self, config):
        """PATCH /api/users/me without a token returns 401."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.patch("/api/users/me", data=json.dumps({"firstname": "X"}),
                                  headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 401)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_password_change_success(self, config):
        """POST /api/users/me/password changes password when current_password is correct."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        from argon2 import PasswordHasher, Type as ArgonType
        ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1, type=ArgonType.ID)
        known_hash = ph.hash("OldPassword123")
        cnx = db.connect()
        db.run_query(cnx, "UPDATE users SET pass_d = %s WHERE user_id = 1", (known_hash,))
        cnx.close()
        body = {"current_password": "OldPassword123", "new_password": "NewPassword456"}
        response = self.app.post("/api/users/me/password", data=json.dumps(body), headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data["status"])
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT pass_d FROM users WHERE user_id = 1")
        cnx.close()
        self.assertTrue(str(row[0][0]).startswith("$argon2"))
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_password_change_wrong_current(self, config):
        """POST /api/users/me/password with wrong current_password returns 400."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        from argon2 import PasswordHasher, Type as ArgonType
        ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1, type=ArgonType.ID)
        known_hash = ph.hash("CorrectPassword123")
        cnx = db.connect()
        db.run_query(cnx, "UPDATE users SET pass_d = %s WHERE user_id = 1", (known_hash,))
        cnx.close()
        body = {"current_password": "WrongPassword999", "new_password": "NewPassword456"}
        response = self.app.post("/api/users/me/password", data=json.dumps(body), headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 400)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_me_password_change_too_short(self, config):
        """POST /api/users/me/password with new_password shorter than 8 chars returns 422."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        body = {"current_password": "anything", "new_password": "short"}
        response = self.app.post("/api/users/me/password", data=json.dumps(body), headers=self.headers_no_admin)
        self.assertEqual(response.status_code, 422)
        os.environ.pop("HEVELIUS_DB_NAME")

    @use_repository
    def test_users_full_list_has_all_fields(self, config):
        """GET /api/users returns all non-password fields for every user."""
        os.environ["HEVELIUS_DB_NAME"] = config["database"]
        response = self.app.get("/api/users", headers=self.headers_admin)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        u = next(x for x in data["users"] if x["user_id"] == 1)
        for field in ("user_id", "login", "firstname", "lastname", "email",
                      "phone", "permissions", "aavso_id", "share", "login_enabled"):
            self.assertIn(field, u)
        for secret in ("pass", "pass_d"):
            self.assertNotIn(secret, u)
        os.environ.pop("HEVELIUS_DB_NAME")


if __name__ == '__main__':
    unittest.main()
