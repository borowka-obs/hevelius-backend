from hevelius import db
import unittest
from tests.dbtest import use_repository


class DbTest(unittest.TestCase):

    @use_repository
    def test_db_version_get(self, config):
        """Test that the database schema version is correct."""

        conn = db.connect(config)
        version = db.version_get(conn)
        conn.close()

        self.assertEqual(version, 11)

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

        # For test data, see db/test-data.psql

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
