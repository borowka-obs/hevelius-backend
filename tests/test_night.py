"""
Tests hevelius.night: the NINA "date - 12h" night identity rule
(night_date), plus the OS-3 astronomy primitives extracted from
hevelius/asteroid.py (get_night_times, moon_rise_set, transit_altitude_deg,
ha_window_visible) and the new sun/moon helpers
(sun_altitude_deg, moon_separation_deg, moon_illumination_pct).
"""

import datetime

import numpy as np
import pytest
from astropy.coordinates import EarthLocation, get_body, get_sun
from astropy.time import Time
from astropy import units as u

from hevelius import night
from hevelius.night import night_date

WARSAW = "Europe/Warsaw"
UTC = datetime.timezone.utc


# Worked examples from the issue: site in Europe/Warsaw (UTC+2, CEST, in
# August), evening / late-night / next-afternoon cases.
@pytest.mark.parametrize("utc_time, expected_date", [
    # Local 2026-08-03 22:00 CEST -> UTC 2026-08-03 20:00
    (datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 3)),
    # Local 2026-08-04 03:00 CEST -> UTC 2026-08-04 01:00
    (datetime.datetime(2026, 8, 4, 1, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 3)),
    # Local 2026-08-04 13:00 CEST -> UTC 2026-08-04 11:00
    (datetime.datetime(2026, 8, 4, 11, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 4)),
])
def test_night_date_worked_examples(utc_time, expected_date):
    assert night_date(utc_time, WARSAW) == expected_date


def test_night_date_boundary_at_local_noon():
    """Local 12:00:00 minus 12h lands exactly on local midnight: same day."""
    utc_time = datetime.datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)  # local 12:00:00 CEST
    assert night_date(utc_time, WARSAW) == datetime.date(2026, 8, 4)


def test_night_date_boundary_just_before_local_noon():
    """One second earlier, it rolls back onto the previous night."""
    utc_time = datetime.datetime(2026, 8, 4, 9, 59, 59, tzinfo=UTC)  # local 11:59:59 CEST
    assert night_date(utc_time, WARSAW) == datetime.date(2026, 8, 3)


def test_night_date_naive_datetime_assumed_utc():
    """A naive datetime is treated as if it were already UTC."""
    aware = datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC)
    naive = datetime.datetime(2026, 8, 3, 20, 0, 0)
    assert night_date(naive, WARSAW) == night_date(aware, WARSAW)


def test_night_date_aware_datetime_in_other_timezone_is_converted():
    """The same instant, expressed in a different zone, gives the same result."""
    utc_time = datetime.datetime(2026, 8, 4, 1, 0, 0, tzinfo=UTC)
    eastern_time = utc_time.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
    assert night_date(eastern_time, WARSAW) == night_date(utc_time, WARSAW)


def test_night_date_utc_site():
    """A telescope with tz_name='UTC' just applies the -12h rule directly."""
    utc_time = datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC)
    assert night_date(utc_time, "UTC") == datetime.date(2026, 8, 3)


# --- OS-3 primitives ---------------------------------------------------

SITE = EarthLocation(lat=52.2 * u.deg, lon=21.0 * u.deg, height=100 * u.m)


class TestTransitAltitudeDeg:
    def test_matches_90_minus_abs_lat_minus_dec(self):
        assert night.transit_altitude_deg(dec_deg=10.0, lat_deg=52.2) == pytest.approx(47.8)
        assert night.transit_altitude_deg(dec_deg=52.2, lat_deg=52.2) == pytest.approx(90.0)
        assert night.transit_altitude_deg(dec_deg=-37.8, lat_deg=52.2) == pytest.approx(0.0)


class TestHaWindowVisible:
    def test_circumpolar_object_always_visible_regardless_of_ra(self):
        # dec close to the pole at a mid-northern latitude: never sets below
        # alt_min=0, so the RA vs LST relationship doesn't matter.
        assert night.ha_window_visible(
            ra_deg=0.0, dec_deg=89.9, lat_deg=52.2,
            lst_mid_deg=180.0, night_half_h=4.0, alt_min_deg=0.0,
        ) is True

    def test_object_that_never_rises_above_alt_min(self):
        # dec far enough south of the horizon at this latitude that even
        # transit altitude is negative: never visible, any RA/LST.
        assert night.ha_window_visible(
            ra_deg=0.0, dec_deg=-89.9, lat_deg=52.2,
            lst_mid_deg=180.0, night_half_h=4.0, alt_min_deg=0.0,
        ) is False

    def test_transit_at_midnight_is_visible_within_narrow_window(self):
        # dec == lat: zenith (90 deg) at transit. RA == LST at midnight, so
        # the object transits exactly at the centre of the night window.
        assert night.ha_window_visible(
            ra_deg=100.0, dec_deg=52.2, lat_deg=52.2,
            lst_mid_deg=100.0, night_half_h=1.0, alt_min_deg=70.0,
        ) is True

    def test_transit_far_from_night_window_is_not_visible(self):
        # Same dec/alt_min (visibility window is +-~33 deg of HA around
        # transit), but the object's transit is 100 deg of HA away from a
        # narrow (+-15 deg) night window: no overlap.
        assert night.ha_window_visible(
            ra_deg=200.0, dec_deg=52.2, lat_deg=52.2,
            lst_mid_deg=100.0, night_half_h=1.0, alt_min_deg=70.0,
        ) is False


class TestGetNightTimes:
    def test_night_window_brackets_sunset_to_sunrise(self):
        start, end = night.get_night_times(SITE, Time("2026-07-22 00:00:00"))
        assert start < end
        # Evening-to-morning, not the old daytime fallback.
        assert start.iso[:10] != end.iso[:10]
        assert int(start.iso[11:13]) >= 15
        assert int(end.iso[11:13]) < 8


class TestMoonRiseSet:
    def test_returns_times_within_padded_window(self):
        night_start, night_end = night.get_night_times(SITE, Time("2026-07-22 00:00:00"))
        moonrise, moonset = night.moon_rise_set(SITE, night_start, night_end)
        pad = 6 * u.hour
        if moonrise is not None:
            assert night_start - pad <= moonrise <= night_end + pad
        if moonset is not None:
            assert night_start - pad <= moonset <= night_end + pad


class TestSunAltitudeDeg:
    def test_near_zero_at_geometric_sunset(self):
        sunset, _sunrise = night.get_night_times(SITE, Time("2026-07-22 00:00:00"))
        assert night.sun_altitude_deg(sunset, SITE) == pytest.approx(0.0, abs=0.1)

    def test_negative_in_the_middle_of_the_night(self):
        sunset, sunrise = night.get_night_times(SITE, Time("2026-07-22 00:00:00"))
        midpoint = sunset + (sunrise - sunset) / 2
        assert night.sun_altitude_deg(midpoint, SITE) < -5.0

    def test_positive_around_local_midday(self):
        # lon=21E -> local solar noon is roughly UTC 10:40; well within
        # daytime in July at this latitude.
        assert night.sun_altitude_deg(Time("2026-07-22 11:00:00"), SITE) > 10.0


class TestMoonSeparationDeg:
    def test_zero_at_the_moons_own_position(self):
        t = Time("2026-07-22 22:00:00")
        moon = get_body("moon", t, location=SITE)
        sep = night.moon_separation_deg(moon.ra.deg, moon.dec.deg, t, SITE)
        assert sep == pytest.approx(0.0, abs=0.05)

    def test_maximal_at_the_antipodal_point(self):
        t = Time("2026-07-22 22:00:00")
        moon = get_body("moon", t, location=SITE)
        anti_ra = (moon.ra.deg + 180.0) % 360.0
        anti_dec = -moon.dec.deg
        sep = night.moon_separation_deg(anti_ra, anti_dec, t, SITE)
        assert sep > 170.0


class TestMoonIlluminationPct:
    def test_matches_elongation_based_formula(self):
        t = Time("2026-07-22 22:00:00")
        sun = get_sun(t)
        moon = get_body("moon", t)
        elongation = sun.separation(moon)
        phase_angle = (180.0 * u.deg) - elongation
        expected = float(np.clip((1.0 + np.cos(phase_angle.to(u.rad).value)) / 2.0, 0.0, 1.0) * 100.0)
        assert night.moon_illumination_pct(t) == pytest.approx(expected, abs=1e-6)

    def test_bounded_between_0_and_100(self):
        for day in range(0, 28, 4):  # sample across roughly one lunar month
            t = Time("2026-07-01 00:00:00") + day * u.day
            pct = night.moon_illumination_pct(t)
            assert 0.0 <= pct <= 100.0

    def test_higher_elongation_gives_higher_illumination(self):
        t1 = Time("2026-07-22 22:00:00")
        t2 = Time("2026-07-30 22:00:00")
        e1 = get_sun(t1).separation(get_body("moon", t1)).deg
        e2 = get_sun(t2).separation(get_body("moon", t2)).deg
        v1 = night.moon_illumination_pct(t1)
        v2 = night.moon_illumination_pct(t2)
        assert e1 != pytest.approx(e2, abs=1.0)  # sanity: dates actually differ in phase
        if e1 > e2:
            assert v1 > v2
        else:
            assert v2 > v1
