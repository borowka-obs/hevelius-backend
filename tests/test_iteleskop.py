from hevelius import iteleskop
import unittest


class ConfigTest(unittest.TestCase):

    def test_parse_iteleskop_filename(self):

        cases = [{"fname": "__DB_2016-02-03_2247-30_J000663_SSVB_HA_1x1_0150s_M78.fit",
                  "exp": {
                      "flags": "__DB",
                      "date": "2016-02-03_2247-30",
                      "task_id": 663,
                      "user": "SSVB",
                      "filter": "HA",
                      "binning": 1,
                      "exposure": 150,
                      "object": "M78",
                      "solve": False,
                      "solved": False,
                      "calibrate": False,
                      "calibrated": False
                  }
                  },
                 {"fname": "S_DB_2016-03-03_22-29-14_J000758__AWE_HA_1x1_1200s_M1.fit",
                  "exp": {
                      "flags": "S_DB",
                      "date": "2016-03-03_22-29-14",
                      "task_id": 758,
                      "user": "AWE",
                      "filter": "HA",
                      "binning": 1,
                      "exposure": 1200,
                      "object": "M1",
                      "solve": True,
                      "solved": True,
                      "calibrate": False,
                      "calibrated": False
                  }
                  },

                 ]

        for case in cases:
            details = iteleskop.parse_iteleskop_filename(case["fname"])

            exp = case["exp"]
            exp["imagename"] = case["fname"]

            self.assertEqual(details, exp)
