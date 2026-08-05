"""
Generic target-visibility engine (OS-3).

Answers "is this RA/Dec target visible tonight, and roughly when" for a
single target with fixed sky coordinates. This is the shared engine Night
Plan (OS-4, #46) calls for both tasks and projects, deliberately generic
over `(ra_deg, dec_deg, constraints)` rather than task/project-specific:
callers do their own table-specific SQL pre-filtering (scope match,
state/date window, mount `min_dec`/`max_dec` - stage 1 below) before
calling in here, so this module doesn't need to know about `tasks` or
`projects` at all.

Reuses the same cheap-filters-first structure `hevelius asteroid visible`
(`hevelius/asteroid.py`) already uses against ~1M rows, staged so that
expensive checks only ever run on survivors of the cheap ones:

  1. SQL pre-filter (scope match, state/date window, mount min_dec/max_dec)
     - caller's responsibility, not implemented here (table-specific).
  2. Transit-altitude check (one subtraction).
  3. Night hour-angle overlap (trig, no frame transform).
  4. Representative-moment check (sun altitude, moon separation/phase).
  5. Precise astropy GCRS/ICRS -> AltAz confirm, survivors only.

Unlike `asteroid.py`'s moving targets (which need one Kepler-orbit solve
per check time), tasks and projects have fixed RA/Dec, so the "check
moment" here is derived directly from the target's transit time rather
than refined iteratively: the transit time if it falls inside the night
window, else whichever edge of the night (sunset or sunrise) is closest
to transit, for targets only above the horizon near one edge of the
night (§4.2 of `doc/observation-scheduler-plan.md`).
"""

from dataclasses import dataclass
from typing import Optional

from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from astropy import units as u

from hevelius import night

# Fallback altitude floor (degrees) when a target has no min_alt constraint
# set (tasks.min_alt / projects.min_alt are nullable - see OS-2). Matches
# the default hevelius/asteroid.py's own `compute_visibility` uses, so an
# unconstrained target isn't silently treated as visible all the way down
# to the mathematical horizon.
DEFAULT_MIN_ALT_DEG = 20.0

# Exclusion reason codes, matching doc/observation-scheduler-plan.md §4.3
# ("explain mode"). `outside_mount_dec_range`, `outside_date_window`,
# `filter_not_on_scope`, `already_complete`, `wrong_state` and
# `min_interval_not_elapsed` are stage-1 (SQL pre-filter) concerns owned by
# the caller, not raised here.
REASON_BELOW_MIN_ALTITUDE = "below_min_altitude"
REASON_SUN_TOO_HIGH = "sun_too_high"
REASON_MOON_TOO_CLOSE = "moon_too_close"
REASON_MOON_PHASE_TOO_BRIGHT = "moon_phase_too_bright"


def ra_hours_to_deg(ra_hours: float) -> float:
    """
    Convert `tasks.ra`/`projects.ra` (stored in hours, 0-24) to the degrees
    (0-360) this module and `hevelius/asteroid.py` work in.

    This is the one boundary conversion the whole engine depends on getting
    right (§1.2 of the plan doc): mixing up hours and degrees silently
    mis-places every target by a factor of 15 rather than raising an
    out-of-range error you'd notice immediately.
    """
    return ra_hours * 15.0


@dataclass
class Constraints:
    """
    Observing constraints for one target, mirroring the `tasks`/`projects`
    columns added in OS-2. All fields are optional/nullable, matching the
    DB columns: `None` means "no constraint of this kind" - except
    `min_alt`, which always falls back to `DEFAULT_MIN_ALT_DEG` (see its
    docstring), since "no altitude floor at all" is never physically
    meaningful.
    """
    min_alt: Optional[float] = None
    moon_distance: Optional[float] = None
    max_moon_phase: Optional[float] = None
    max_sun_alt: Optional[float] = None


@dataclass
class VisibilityResult:
    """
    Outcome of `check_visibility` for one target.

    `reason` is `None` when `visible` is True. Diagnostic fields
    (`sun_altitude_deg`, `moon_separation_deg`, `moon_illumination_pct`) are
    populated as far as the staged pipeline got before a rejection (or all
    the way through, when visible) - useful for `?explain=true` (OS-4)
    without recomputing anything.
    """
    visible: bool
    reason: Optional[str] = None
    check_time: Optional[Time] = None
    altitude_deg: Optional[float] = None
    azimuth_deg: Optional[float] = None
    sun_altitude_deg: Optional[float] = None
    moon_separation_deg: Optional[float] = None
    moon_illumination_pct: Optional[float] = None


def _transit_offset_h(ra_deg: float, lst_mid_deg: float) -> float:
    """Hours from night midpoint to upper transit (negative = transit before midnight)."""
    ha_mid_deg = ((lst_mid_deg - ra_deg) + 180.0) % 360.0 - 180.0
    return -ha_mid_deg / 15.0


def _representative_check_time(
    ra_deg: float,
    lst_mid_deg: float,
    t_mid: Time,
    night_half_h: float,
    night_start: Time,
    night_end: Time,
) -> Time:
    """
    Moment within the night to run stages 4 and 5 against: transit time if
    it falls inside the night window (fixed RA/Dec means that's a direct
    hour-angle computation, no orbit propagation needed); otherwise the
    target is only above the horizon near one edge of the night, so use
    whichever edge is closest to its transit - sunset if transit is before
    the night starts (the target is already descending all night), sunrise
    if transit is after the night ends (still rising all night).

    Using astronomical midnight here for an evening-only or morning-only
    target would check sun/moon conditions and altitude at a moment the
    target isn't even above `min_alt` (stage 3 only confirmed *some* moment
    in the night qualifies, not that midnight is it), which can both
    wrongly reject the target (stage 5) and wrongly evaluate sun/moon
    constraints against a moment the target was never observable at
    (stage 4).
    """
    transit_offset_h = _transit_offset_h(ra_deg, lst_mid_deg)
    if abs(transit_offset_h) <= night_half_h:
        return t_mid + transit_offset_h * u.hour
    if transit_offset_h < -night_half_h:
        return night_start
    return night_end


def check_visibility(
    ra_deg: float,
    dec_deg: float,
    constraints: Constraints,
    location: EarthLocation,
    night_start: Time,
    night_end: Time,
) -> VisibilityResult:
    """
    Run the stage 2-5 visibility pipeline for one fixed-RA/Dec target.

    `night_start`/`night_end` are the actual sunset/sunrise window (e.g.
    from `hevelius.night.get_night_times`), not the coarser night-identity
    window from `night_date`.
    """
    night._configure_iers_for_planning()

    min_alt = constraints.min_alt if constraints.min_alt is not None else DEFAULT_MIN_ALT_DEG
    lat_deg = location.lat.deg

    # Stage 2: transit-altitude check (one subtraction).
    transit_alt = night.transit_altitude_deg(dec_deg, lat_deg)
    if transit_alt < min_alt:
        return VisibilityResult(visible=False, reason=REASON_BELOW_MIN_ALTITUDE)

    # Stage 3: night hour-angle overlap (trig, no frame transform).
    night_half_h = (night_end - night_start).to(u.hour).value / 2.0
    t_mid = night_start + night_half_h * u.hour
    lst_mid_deg = t_mid.sidereal_time("apparent", longitude=location.lon).deg
    if not night.ha_window_visible(ra_deg, dec_deg, lat_deg, lst_mid_deg, night_half_h, min_alt):
        return VisibilityResult(visible=False, reason=REASON_BELOW_MIN_ALTITUDE)

    t_check = _representative_check_time(
        ra_deg, lst_mid_deg, t_mid, night_half_h, night_start, night_end,
    )

    # Stage 4: representative-moment check (sun altitude, moon separation/phase).
    sun_alt = night.sun_altitude_deg(t_check, location)
    if constraints.max_sun_alt is not None and sun_alt > constraints.max_sun_alt:
        return VisibilityResult(
            visible=False, reason=REASON_SUN_TOO_HIGH,
            check_time=t_check, sun_altitude_deg=round(sun_alt, 2),
        )

    moon_sep = night.moon_separation_deg(ra_deg, dec_deg, t_check, location)
    if constraints.moon_distance is not None and moon_sep < constraints.moon_distance:
        return VisibilityResult(
            visible=False, reason=REASON_MOON_TOO_CLOSE,
            check_time=t_check, sun_altitude_deg=round(sun_alt, 2),
            moon_separation_deg=round(moon_sep, 2),
        )

    moon_illum = night.moon_illumination_pct(t_check)
    if constraints.max_moon_phase is not None and moon_illum > constraints.max_moon_phase:
        return VisibilityResult(
            visible=False, reason=REASON_MOON_PHASE_TOO_BRIGHT,
            check_time=t_check, sun_altitude_deg=round(sun_alt, 2),
            moon_separation_deg=round(moon_sep, 2), moon_illumination_pct=round(moon_illum, 2),
        )

    # Stage 5: precise astropy ICRS -> AltAz confirm, survivors only.
    target = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    altaz = target.transform_to(AltAz(obstime=t_check, location=location))
    alt_deg = float(altaz.alt.to(u.deg).value)
    az_deg = float(altaz.az.to(u.deg).value)

    if alt_deg < min_alt:
        return VisibilityResult(
            visible=False, reason=REASON_BELOW_MIN_ALTITUDE,
            check_time=t_check, altitude_deg=round(alt_deg, 2), azimuth_deg=round(az_deg, 2),
            sun_altitude_deg=round(sun_alt, 2), moon_separation_deg=round(moon_sep, 2),
            moon_illumination_pct=round(moon_illum, 2),
        )

    return VisibilityResult(
        visible=True,
        check_time=t_check,
        altitude_deg=round(alt_deg, 2),
        azimuth_deg=round(az_deg, 2),
        sun_altitude_deg=round(sun_alt, 2),
        moon_separation_deg=round(moon_sep, 2),
        moon_illumination_pct=round(moon_illum, 2),
    )
