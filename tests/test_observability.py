"""
Tests hevelius.observability: the generic (ra_deg, dec_deg, constraints)
staged visibility pipeline (OS-3) that Night Plan (OS-4, #46) will call for
tasks and projects.
"""

import pytest
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy import units as u

from hevelius import night, observability
from hevelius.observability import Constraints

SITE = EarthLocation(lat=52.2 * u.deg, lon=21.0 * u.deg, height=100 * u.m)
NIGHT_START, NIGHT_END = night.get_night_times(SITE, Time("2026-07-22 00:00:00"))
_T_MID = NIGHT_START + (NIGHT_END - NIGHT_START) / 2
_LST_MID_DEG = _T_MID.sidereal_time("apparent", longitude=SITE.lon).deg

# A target with dec == site latitude transits at the zenith; RA == LST at
# midnight makes it transit exactly at the centre of the night window, so
# it's comfortably visible under permissive constraints.
ZENITH_DEC = SITE.lat.deg
MIDNIGHT_TRANSIT_RA = _LST_MID_DEG


class TestRaHoursToDeg:
    """§1.2: the RA hours->degrees boundary conversion, guarded on its own."""

    def test_conversion_factor_of_15(self):
        assert observability.ra_hours_to_deg(0.0) == 0.0
        assert observability.ra_hours_to_deg(1.0) == 15.0
        assert observability.ra_hours_to_deg(12.0) == 180.0

    def test_full_range_maps_onto_full_circle(self):
        # tasks.ra / projects.ra are validated 0-24h (TaskAddRequestSchema);
        # confirm that range maps onto the full 0-360 degree circle used by
        # this module and hevelius/asteroid.py.
        assert observability.ra_hours_to_deg(0.0) == 0.0
        assert observability.ra_hours_to_deg(24.0) == 360.0


class TestCheckVisibilityStaging:
    def test_below_min_altitude_short_circuits_before_any_sun_moon_check(self):
        # Transit altitude alone (90 - |lat - dec|) already rules this out
        # at a mid-northern latitude: stage 2 rejects before stage 3/4/5 run.
        result = observability.check_visibility(
            ra_deg=0.0, dec_deg=-80.0, constraints=Constraints(),
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_BELOW_MIN_ALTITUDE
        assert result.check_time is None  # rejected before stage 3

    def test_visible_target_with_no_constraints_beyond_default_min_alt(self):
        result = observability.check_visibility(
            ra_deg=MIDNIGHT_TRANSIT_RA, dec_deg=ZENITH_DEC, constraints=Constraints(),
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is True
        assert result.reason is None
        assert result.altitude_deg > observability.DEFAULT_MIN_ALT_DEG
        assert result.azimuth_deg is not None
        assert result.sun_altitude_deg < 0  # it's nighttime
        assert result.moon_separation_deg is not None
        assert result.moon_illumination_pct is not None

    def test_sun_too_high_rejects_when_constraint_stricter_than_actual(self):
        actual_sun_alt = night.sun_altitude_deg(_T_MID, SITE)
        constraints = Constraints(max_sun_alt=actual_sun_alt - 5.0)
        result = observability.check_visibility(
            ra_deg=MIDNIGHT_TRANSIT_RA, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_SUN_TOO_HIGH
        assert result.sun_altitude_deg is not None

    def test_moon_too_close_rejects_when_constraint_stricter_than_actual(self):
        actual_sep = night.moon_separation_deg(MIDNIGHT_TRANSIT_RA, ZENITH_DEC, _T_MID, SITE)
        constraints = Constraints(moon_distance=actual_sep + 10.0)
        result = observability.check_visibility(
            ra_deg=MIDNIGHT_TRANSIT_RA, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_MOON_TOO_CLOSE
        assert result.moon_separation_deg is not None

    def test_moon_phase_too_bright_rejects_when_constraint_stricter_than_actual(self):
        actual_illum = night.moon_illumination_pct(_T_MID)
        constraints = Constraints(max_moon_phase=actual_illum - 1.0)
        result = observability.check_visibility(
            ra_deg=MIDNIGHT_TRANSIT_RA, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_MOON_PHASE_TOO_BRIGHT
        assert result.moon_illumination_pct is not None

    def test_permissive_constraints_pass_all_stages(self):
        constraints = Constraints(min_alt=10.0, moon_distance=0.0, max_moon_phase=100.0, max_sun_alt=90.0)
        result = observability.check_visibility(
            ra_deg=MIDNIGHT_TRANSIT_RA, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is True
        assert result.reason is None

    def test_evening_target_visible_when_above_min_alt_at_sunset_not_at_midnight(self):
        # Transit is before the night window: stage 3 overlap passes, but altitude
        # at night midpoint is below min_alt. Stage 5 must check at sunset.
        evening_transit_ra = 124.4
        night_half_h = (NIGHT_END - NIGHT_START).to(u.hour).value / 2.0
        assert night.ha_window_visible(
            evening_transit_ra, ZENITH_DEC, SITE.lat.deg, _LST_MID_DEG,
            night_half_h, observability.DEFAULT_MIN_ALT_DEG,
        )
        result = observability.check_visibility(
            ra_deg=evening_transit_ra, dec_deg=ZENITH_DEC, constraints=Constraints(),
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is True
        assert result.reason is None
        assert result.altitude_deg >= observability.DEFAULT_MIN_ALT_DEG
        assert result.check_time == NIGHT_START

    def test_morning_target_visible_when_above_min_alt_at_sunrise_not_at_midnight(self):
        # Transit is after the night window: stage 3 overlap passes, but altitude
        # at night midpoint is below min_alt. Stage 5 must check at sunrise.
        morning_transit_ra = 82.4
        night_half_h = (NIGHT_END - NIGHT_START).to(u.hour).value / 2.0
        assert night.ha_window_visible(
            morning_transit_ra, ZENITH_DEC, SITE.lat.deg, _LST_MID_DEG,
            night_half_h, observability.DEFAULT_MIN_ALT_DEG,
        )
        result = observability.check_visibility(
            ra_deg=morning_transit_ra, dec_deg=ZENITH_DEC, constraints=Constraints(),
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is True
        assert result.reason is None
        assert result.altitude_deg >= observability.DEFAULT_MIN_ALT_DEG
        assert result.check_time == NIGHT_END

    def test_evening_target_sun_check_runs_at_sunset_not_midnight(self):
        # Same evening-only target as above. At sunset the Sun is at ~0 deg;
        # at midnight it's the night's most negative. A max_sun_alt constraint
        # that only the midnight value would satisfy must still reject here,
        # since sunset - not midnight - is the only moment this target is up.
        evening_transit_ra = 124.4
        sun_alt_at_sunset = night.sun_altitude_deg(NIGHT_START, SITE)
        sun_alt_at_midnight = night.sun_altitude_deg(_T_MID, SITE)
        assert sun_alt_at_sunset > sun_alt_at_midnight  # sanity: sunset is brighter
        constraints = Constraints(max_sun_alt=(sun_alt_at_sunset + sun_alt_at_midnight) / 2)
        result = observability.check_visibility(
            ra_deg=evening_transit_ra, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_SUN_TOO_HIGH
        assert result.check_time == NIGHT_START
        assert result.sun_altitude_deg == pytest.approx(sun_alt_at_sunset, abs=0.01)

    def test_morning_target_sun_check_runs_at_sunrise_not_midnight(self):
        # Mirror of the sunset case: this target is only up at sunrise, so
        # the sun/moon check (stage 4) must use sunrise, not midnight.
        morning_transit_ra = 82.4
        sun_alt_at_sunrise = night.sun_altitude_deg(NIGHT_END, SITE)
        sun_alt_at_midnight = night.sun_altitude_deg(_T_MID, SITE)
        assert sun_alt_at_sunrise > sun_alt_at_midnight  # sanity: sunrise is brighter
        constraints = Constraints(max_sun_alt=(sun_alt_at_sunrise + sun_alt_at_midnight) / 2)
        result = observability.check_visibility(
            ra_deg=morning_transit_ra, dec_deg=ZENITH_DEC, constraints=constraints,
            location=SITE, night_start=NIGHT_START, night_end=NIGHT_END,
        )
        assert result.visible is False
        assert result.reason == observability.REASON_SUN_TOO_HIGH
        assert result.check_time == NIGHT_END
        assert result.sun_altitude_deg == pytest.approx(sun_alt_at_sunrise, abs=0.01)
