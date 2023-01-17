from hevelius import config
import unittest


class ConfigTest(unittest.TestCase):

    def test_variables(self):
        """Checks if hevelius.config defines necessary configuration parameters."""
        self.assertTrue(config.USER and type(config.USER) == str)
        self.assertTrue(config.DBNAME and type(config.USER) == str)
        self.assertTrue(config.PASSWORD and type(config.USER) == str)
        self.assertTrue(config.PORT and type(config.PORT) == int)
        self.assertTrue(config.TYPE and type(config.TYPE) ==
                        str and config.TYPE in ['mysql', 'pgsql'])

        # Uncomment this once REPO_PATH is implemented
        # self.assertTrue(config.REPO_PATH and type(config.USER) == str)
