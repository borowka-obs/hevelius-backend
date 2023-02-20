"""
Tests utility functions
"""

import unittest
import pytest
from hevelius.utils import deg2rah, hm2deg, parse_ra, parse_dec, format_ra, format_dec, constellation2abbrev, abbrev2constellation


# test written by ChatGPT (☉_☉)
@pytest.mark.parametrize('h, m, deg', [
    (0, 0, 0),
    (14, 30, 217.5),
    (8, 47, 131.75)
])
def test_hm2deg(h, m, deg):
    """tests if hour/min notation for Right Ascension can be converted to float"""
    assert hm2deg(h, m) == deg


# Tests deg2rah - converts degrees to Right Ascension, expressed as XXhYYm
# (ZZZdeg), written by ChatGPT (☉_☉)
@pytest.mark.parametrize('ra, h, m', [
    (0, 0, 0),
    (217.5, 14, 30),
    (131.75, 8, 47)
])
def test_deg2rah(ra: float, h: int, m: int):
    """Tests if Right Ascension (in degress) can be converted to h m format"""
    result = deg2rah(ra)
    expected = "{}h{}{}m ({:.02f}deg)".format(h, m, "0" if m < 10 else "", ra)

    result = deg2rah(ra)
    assert result == expected


class TestParse(unittest.TestCase):
    """Tests parsing functions (parse_ra, parse_dec)"""

    def test_parse_ra(self):
        """Tests if Right Ascension can be parsed properly"""
        self.assertAlmostEqual(parse_ra('11 22 33'), 11.37583333)
        self.assertAlmostEqual(parse_ra('11 22'), 11.36666666)
        self.assertAlmostEqual(parse_ra('11h22m33s'), 11.37583333)
        self.assertAlmostEqual(parse_ra('11h22m33.4s'), 11.375944444444)
        self.assertAlmostEqual(parse_ra('11.2345'), 11.2345)

    def test_parse_dec(self):
        """Tests if declination can be parsed properly"""
        self.assertAlmostEqual(parse_dec('11 22 33'), 11.37583333)
        self.assertAlmostEqual(parse_dec('+11 22 33'), 11.37583333)
        self.assertAlmostEqual(parse_dec('-11 22 33'), -11.37583333)
        self.assertAlmostEqual(parse_dec('11 22'), 11.36666666)
        self.assertAlmostEqual(parse_dec('+11 22'), 11.36666666)
        self.assertAlmostEqual(parse_dec('-11 22'), -11.36666666)
        self.assertAlmostEqual(parse_dec('11d22m33s'), 11.37583333)
        self.assertAlmostEqual(parse_dec('+11d22m33s'), 11.37583333)
        self.assertAlmostEqual(parse_dec('-11d22m33s'), -11.37583333)
        self.assertAlmostEqual(parse_dec('11 22m33.4s'), 11.375944444444)
        self.assertAlmostEqual(parse_dec('+11 22m33.4s'), 11.375944444444)
        self.assertAlmostEqual(parse_dec('-11 22m33.4s'), -11.375944444444)
        self.assertAlmostEqual(parse_dec('11.2345'), 11.2345)
        self.assertAlmostEqual(parse_dec('+11.2345'), 11.2345)
        self.assertAlmostEqual(parse_dec('-11.2345'), -11.2345)


class TestFormat(unittest.TestCase):
    """Tests printing functions: format_ra, format_dec"""

    def test_format_ra(self):
        """Tests if Right Ascension can be formatted properly"""
        self.assertEqual(format_ra(8.3156), '08 18 56.2')
        self.assertEqual(format_ra(17.25), '17 15 00.0')

    def test_format_dec(self):
        """Tests if declination can be formatted properly"""
        self.assertEqual(format_dec(8.3156), '08 18 56.2')
        self.assertEqual(format_dec(17.25), '17 15 00.0')
        self.assertEqual(format_dec(-8.3156), '-08 18 56.2')
        self.assertEqual(format_dec(-17.25), '-17 15 00.0')


class TestConstellationNames(unittest.TestCase):
    def setUp(self):
        self.test_data = {
            'And': 'Andromeda',
            'Aqr': 'Aquarius',
            'CMa': 'Canis Major',
            'Lup': 'Lupus',
            'Vir': 'Virgo'
            }

    def test_constellation2abbrev(self):
        self.assertEqual(constellation2abbrev('Andromeda'), 'And')
        self.assertEqual(constellation2abbrev('Antlia'), 'Ant')
        self.assertEqual(constellation2abbrev('Apus'), 'Aps')
        self.assertEqual(constellation2abbrev('Aquarius'), 'Aqr')
        self.assertEqual(constellation2abbrev('Aquila'), 'Aql')
        self.assertEqual(constellation2abbrev('Ara'), 'Ara')
        self.assertEqual(constellation2abbrev('Aries'), 'Ari')
        self.assertEqual(constellation2abbrev('Auriga'), 'Aur')
        self.assertEqual(constellation2abbrev('Boötes'), 'Boo')
        self.assertEqual(constellation2abbrev('Caelum'), 'Cae')
        self.assertEqual(constellation2abbrev('Camelopardalis'), 'Cam')
        self.assertEqual(constellation2abbrev('Cancer'), 'Cnc')

    def test_invalid_constellations(self):
        with self.assertRaises(ValueError):
            constellation2abbrev('invalid_string')

    def test_abbreviation_to_constellation(self):
        for abbr, expected_result in self.test_data.items():
            result = abbrev2constellation(abbr)
            self.assertEqual(
                result,
                expected_result,
                msg=f"Failed for abbr: {abbr} Result: {result}, Expected Result: {expected_result}"
            )

    def test_value_error_raised(self):
        with self.assertRaises(ValueError):
            abbrev2constellation('Plo')
