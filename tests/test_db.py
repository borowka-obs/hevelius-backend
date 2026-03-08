import os
from hevelius import db
from hevelius.cmd_equipment import add_filter, edit_filter, set_filter_active, add_sensor, edit_sensor
import unittest
from tests.dbtest import use_repository


class DbTest(unittest.TestCase):

    @use_repository
    def test_db_version_get(self, config):
        """Test that the database schema version is correct."""

        conn = db.connect(config)
        version = db.version_get(conn)
        conn.close()

        self.assertEqual(version, 15)

    @use_repository
    def test_sensor(self, config):
        """Test that the sensors information can be retrieved."""
        conn = db.connect(config)

        cases = [
            {
                "name": "FLI",
                "exp_sensor_id": 2,
                "exp_name": "FLI Proline 16803",
                "exp_resx": 4096,
                "exp_resy": 4096,
                "exp_pixel_x": 9.0,
                "exp_pixel_y": 9.0,
                "exp_bits": 16,
                "exp_width": 36.8,
                "exp_height": 36.8
            }
        ]

        for case in cases:
            sensor_id, name, resx, resy, pixel_x, pixel_y, bits, width, height = db.sensor_get_by_name(conn, case["name"])
            self.assertAlmostEqual(sensor_id, case['exp_sensor_id'])
            self.assertAlmostEqual(name, case['exp_name'])
            self.assertAlmostEqual(resx, case['exp_resx'])
            self.assertAlmostEqual(resy, case['exp_resy'])
            self.assertAlmostEqual(pixel_x, case['exp_pixel_x'])
            self.assertAlmostEqual(pixel_y, case['exp_pixel_y'])
            self.assertAlmostEqual(bits, case['exp_bits'])
            self.assertAlmostEqual(width, case['exp_width'])
            self.assertAlmostEqual(height, case['exp_height'])

        conn.close()

    @use_repository
    def test_tasks_radius_get1(self, config):
        """Test that tasks can be retrieved by filter."""

        conn = db.connect(config)
        tasks = db.tasks_radius_get(conn, 0, 25, 1, "", "task_id DESC")
        conn.close()

        self.assertGreaterEqual(len(tasks), 10)
        self.assertEqual(tasks[0][0], 87775)
        self.assertEqual(tasks[1][0], 70556)
        self.assertEqual(tasks[2][0], 69426)
        # Let's assume the remaining tasks have correct task_ids, too.

    @use_repository
    def test_tasks_radius_get_filter(self, config):
        """Test that tasks can be retrieved by filter."""

        cases = [
            {"filter": "AND scope_id=1", "exp_count": 7},
            {"filter": "AND scope_id=2", "exp_count": 4},
            {"filter": "AND scope_id=4", "exp_count": 0},
            {"filter": "AND sensor_id=1", "exp_count": 1},
            {"filter": "AND sensor_id=2", "exp_count": 10},
            {"filter": "AND he_resx=3326", "exp_count": 1},
            {"filter": "AND he_resy=2504", "exp_count": 1},
            {"filter": "AND scope_id=4", "exp_count": 0}
        ]

        conn = db.connect(config)

        for case in cases:
            tasks = db.tasks_radius_get(conn, 0, 0, 360, case['filter'], "")
            self.assertEqual(len(tasks), case['exp_count'])

        conn.close()

    @use_repository
    def test_catalog_radius_get2(self, config):
        """Test that objects can be retrieved by radius search."""
        conn = db.connect(config)

        # Test cases with RA in hours (0-24), Dec in degrees (-90 to +90)
        cases2 = [
            {
                "ra": 15.0,  # 15h = 225 degrees
                "dec": 0.0,
                "radius": 360.0,  # all sky
                "exp_count": 11  # Expected number of objects within radius - all 12 objects
            },

            {
                "ra": 12.0,  # 12h = 180 degrees
                "dec": -90.0,
                "radius": 30.0,
                "exp_count": 1  # only one object so far south - Coal Sack
            },

            {
                "ra": 12.0317,
                "dec": -18.87,
                "radius": 0.5,
                "exp_count": 2  # The Antennae galaxies are close to these coordinates
            }
        ]

        for case in cases2:
            objects = db.catalog_radius_get(conn, case["ra"], case["dec"], case["radius"])
            self.assertEqual(len(objects), case["exp_count"],
                             f"Expected {case['exp_count']} objects within {case['radius']} degrees of "
                             f"RA={case['ra']}h DEC={case['dec']}, but found {len(objects)}")

        conn.close()

    @use_repository
    def test_tasks_radius_get(self, config):
        """Test that tasks can be retrieved by radius search."""
        conn = db.connect(config)

        # For test data, see tests/test-data.psql

        # Test cases with RA and Dec in degrees (0-360, -90 to +90)
        cases = [
            {
                "ra": 0.0,
                "dec": 25.0,
                "radius": 3.0,
                "filter": "",
                "exp_count": 10  # Return all Z Peg tasks (10 of them)
            },
            {
                "ra": 0.0,
                "dec": 0.0,
                "radius": 360.0,  # Full sky
                "filter": "",
                "exp_count": 11  # All 11 tasks
            },
            {
                "ra": 12.60,
                "dec": 25.98,
                "radius": 3.0,
                "filter": "",
                "exp_count": 1  # task 800 - ngc 4565
            }
        ]

        for case in cases:
            tasks = db.tasks_radius_get(conn, case["ra"], case["dec"],
                                        case["radius"], case["filter"])
            self.assertEqual(len(tasks), case["exp_count"],
                             f"Expected {case['exp_count']} tasks within {case['radius']} degrees of "
                             f"RA={case['ra']} DEC={case['dec']} with filter '{case['filter']}', "
                             f"but found {len(tasks)}")

            # For tasks that are returned, verify they have all expected fields
            for task in tasks:
                self.assertEqual(len(task), 12)  # Verify all columns are present
                # task_id, object, imagename, he_fwhm, ra, decl, comment,
                # he_resx, he_resy, filter, he_focal, binning
                self.assertIsNotNone(task[0])  # task_id should not be None
                self.assertEqual(type(task[0]), int)  # task_id should be integer

        conn.close()

    @use_repository
    def test_filters_and_telescope_filters(self, config):
        """Test that filters and telescope_filters (schema 15) work."""
        conn = db.connect(config)
        rows = db.run_query(conn, "SELECT filter_id, short_name, full_name, url, active FROM filters ORDER BY filter_id")
        conn.close()
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][1], 'SG')
        self.assertEqual(rows[0][4], True)
        conn = db.connect(config)
        tf = db.run_query(conn, "SELECT scope_id, filter_id FROM telescope_filters ORDER BY scope_id, filter_id")
        conn.close()
        self.assertGreaterEqual(len(tf), 2)
        self.assertIn((1, 1), tf)

    @use_repository
    def test_sensors_have_vendor_url_active(self, config):
        """Test that sensors table has vendor, url, active columns (schema 15)."""
        conn = db.connect(config)
        rows = db.run_query(conn, "SELECT sensor_id, name, vendor, url, active FROM sensors ORDER BY sensor_id LIMIT 1")
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 5)
        self.assertTrue(rows[0][4])  # active defaults to true

    @use_repository
    def test_projects_and_subframes(self, config):
        """Test that projects, project_subframes, project_users, task_projects exist and have data."""
        conn = db.connect(config)
        projects = db.run_query(conn, "SELECT project_id, name, description, ra, decl, active FROM projects ORDER BY project_id")
        conn.close()
        self.assertGreaterEqual(len(projects), 1)
        self.assertEqual(projects[0][1], 'Z Peg campaign')
        conn = db.connect(config)
        sub = db.run_query(conn, "SELECT project_id, filter_id, exposure_time, count, active FROM project_subframes ORDER BY id")
        conn.close()
        self.assertGreaterEqual(len(sub), 1)
        self.assertEqual(sub[0][2], 20)
        self.assertEqual(sub[0][3], 10)
        conn = db.connect(config)
        tp = db.run_query(conn, "SELECT task_id, project_id FROM task_projects LIMIT 3")
        conn.close()
        self.assertGreaterEqual(len(tp), 1)

    @use_repository
    def test_filter_add_edit_activate_deactivate_cli(self, config):
        """CLI: add filter, edit, activate, deactivate."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            # Add new filter
            fid = add_filter("XX", "Test Filter", "https://example.com", active=True)
            self.assertIsNotNone(fid)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT filter_id, short_name, full_name, url, active FROM filters WHERE short_name = 'XX'")
            conn.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][2], "Test Filter")
            self.assertTrue(rows[0][4])
            filter_id = rows[0][0]
            # Edit
            ok = edit_filter(filter_id, full_name="Test Filter Updated", active=False)
            self.assertTrue(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT full_name, active FROM filters WHERE filter_id = %s", (filter_id,))
            conn.close()
            self.assertEqual(rows[0][0], "Test Filter Updated")
            self.assertFalse(rows[0][1])
            # Activate
            ok = set_filter_active(filter_id, True)
            self.assertTrue(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT active FROM filters WHERE filter_id = %s", (filter_id,))
            conn.close()
            self.assertTrue(rows[0][0])
            # Deactivate
            ok = set_filter_active(filter_id, False)
            self.assertTrue(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT active FROM filters WHERE filter_id = %s", (filter_id,))
            conn.close()
            self.assertFalse(rows[0][0])
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)

    @use_repository
    def test_sensor_add_edit_cli(self, config):
        """CLI: add sensor, edit sensor."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        try:
            sid = add_sensor("CLI Test Sensor", resx=1000, resy=1000, pixel_x=4.0, pixel_y=4.0, vendor="CLI", active=True)
            self.assertIsNotNone(sid)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT sensor_id, name, resx, vendor, active FROM sensors WHERE name = 'CLI Test Sensor'")
            conn.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][2], 1000)
            self.assertEqual(rows[0][3], "CLI")
            self.assertTrue(rows[0][4])
            sensor_id = rows[0][0]
            ok = edit_sensor(sensor_id, name="CLI Test Sensor Updated", vendor="CLI-edit")
            self.assertTrue(ok)
            conn = db.connect()
            rows = db.run_query(conn, "SELECT name, vendor FROM sensors WHERE sensor_id = %s", (sensor_id,))
            conn.close()
            self.assertEqual(rows[0][0], "CLI Test Sensor Updated")
            self.assertEqual(rows[0][1], "CLI-edit")
        finally:
            os.environ.pop('HEVELIUS_DB_NAME', None)
