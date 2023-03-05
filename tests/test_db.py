from hevelius import db
import unittest

from tests.dbtest import use_repository


class DbTest(unittest.TestCase):

    @use_repository
    def test_db_version_get(self, config):

        conn = db.connect(config)
        version = db.version_get(conn)
        conn.close()

        self.assertEqual(version, 10)
