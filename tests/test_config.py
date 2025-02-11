from hevelius import config as hevelius_config
import unittest


class ConfigTest(unittest.TestCase):

    def test_variables(self):
        """Checks if hevelius.config defines necessary configuration parameters."""

        cfg = hevelius_config.load_config()

        self.assertTrue(cfg['database']['user'] and isinstance(cfg['database']['user'], str))
        self.assertTrue(cfg['database']['database'] and isinstance(cfg['database']['database'], str))
        self.assertTrue(cfg['database']['password'] and isinstance(cfg['database']['password'], str))
        self.assertTrue(cfg['database']['port'] and isinstance(cfg['database']['port'], int))

        # Uncomment this once REPO_PATH is implemented
        # self.assertTrue(config.REPO_PATH and type(config.USER) == str)
