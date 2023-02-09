import pytest
from hevelius.utils import deg2rah, hm2deg


# test written by ChatGPT (☉_☉)
@pytest.mark.parametrize('h, m, deg', [
    (0, 0, 0),
    (14, 30, 217.5),
    (8, 47, 131.75)
])
def test_hm2deg(h, m, deg):
    assert hm2deg(h, m) == deg


# Tests deg2rah - converts degrees to Right Ascension, expressed as XXhYYm
# (ZZZdeg), written by ChatGPT (☉_☉)
@pytest.mark.parametrize('ra, h, m', [
    (0, 0, 0),
    (217.5, 14, 30),
    (131.75, 8, 47)
])
def test_deg2rah(ra: float, h: int, m: int):
    result = deg2rah(ra)
    expected = "{}h{}{}m ({:.02f}deg)".format(h, m, "0" if m < 10 else "", ra)

    result = deg2rah(ra)
    assert result == expected
