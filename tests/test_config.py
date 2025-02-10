from hevelius import config as hevelius_config
import unittest


class ConfigTest(unittest.TestCase):

    def test_variables(self):
        """Checks if hevelius.config defines necessary configuration parameters."""

        cfg = hevelius_config.load_config()

        self.assertTrue(cfg['DATABASE']['USER'] and isinstance(cfg['DATABASE']['USER'], str))
        self.assertTrue(cfg['DATABASE']['DBNAME'] and isinstance(cfg['DATABASE']['USER'], str))
        self.assertTrue(cfg['DATABASE']['PASSWORD'] and isinstance(cfg['DATABASE']['USER'], str))
        self.assertTrue(cfg['DATABASE']['PORT'] and isinstance(cfg['DATABASE']['PORT'], int))
        self.assertTrue(cfg['DATABASE']['TYPE'] and isinstance(cfg['DATABASE']['TYPE'], str) and cfg['DATABASE']['TYPE'] in ['mysql', 'pgsql'])

        # Uncomment this once REPO_PATH is implemented
        # self.assertTrue(config.REPO_PATH and type(config.USER) == str)
