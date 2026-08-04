"""
Night identity and shared astronomy primitives.

Night identity: which observing night a UTC instant belongs to. Implements
the NINA "date - 12h" rule: convert the instant to the telescope's local
civil time, subtract 12 hours, take the date. A night session that spans
local midnight (e.g. starts at 22:00, ends at 03:00 local) therefore
collapses onto a single calendar date - the evening's date.

Astronomy primitives (night window, moon rise/set, sun altitude, moon
separation/illumination, transit altitude, night hour-angle overlap):
extracted from `hevelius/asteroid.py` (OS-3), which is the one place this
math already existed and was battle-tested against ~1M rows. Behavior is
unchanged for the asteroid-visibility feature; these are now importable
elsewhere too - namely `hevelius/observability.py`, the generic staged
visibility pipeline that Night Plan (OS-4) calls for tasks and projects.

Shared by Night Plan (OS-4), `observation_events.night_date` (OS-8), and
nightly Statistics grouping (OS-9) so all three consumers bucket
observations into nights the same way.
"""

import datetime
from typing import Tuple
from zoneinfo import ZoneInfo

import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body, get_sun
from astropy.time import Time
from astropy import units as u
from astropy.utils import iers


def night_date(t: datetime.datetime, tz_name: str) -> datetime.date:
    """
    Returns the observing night (a date) that the UTC instant `t` belongs
    to at the site identified by the IANA timezone `tz_name`
    (e.g. "Europe/Warsaw").

    `t` may be a naive datetime (assumed to already be UTC) or a
    timezone-aware datetime in any zone (converted to UTC first).
    """
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)

    local = t.astimezone(ZoneInfo(tz_name))
    return (local - datetime.timedelta(hours=12)).date()


def _configure_iers_for_planning() -> None:
    """
    Allow IERS age extrapolation for offline/future observation planning.

    Recent/future dates need up-to-date Earth orientation (IERS) data, normally
    auto-downloaded. Without network access (or if the download fails), astropy
    raises rather than falling back to extrapolated values. The extrapolation
    error is sub-arcsecond and irrelevant for altitude/visibility purposes, so
    disable the hard age limit when running visibility computations.

    Idempotent via the auto_max_age sentinel, so calling it from every public
    function in this module does not repeatedly touch global astropy state.
    """
    if iers.conf.auto_max_age is None:
        return
    iers.conf.auto_max_age = None


def _altitude_series(body_fn, location: EarthLocation, t0: Time, t1: Time, n: int = 481):
    """
    Sample altitude (degrees) of a solar-system body from t0 to t1 inclusive.

    body_fn(times) -> SkyCoord (e.g. get_sun, or lambda t: get_body('moon', t)).
    """
    duration_h = (t1 - t0).to(u.hour).value
    times = t0 + np.linspace(0.0, duration_h, n) * u.hour
    frame = AltAz(obstime=times, location=location)
    alt = body_fn(times).transform_to(frame).alt.to(u.deg).value
    return times, np.asarray(alt, dtype=float)


def _find_zero_crossings(times: Time, alts: np.ndarray, level: float = 0.0):
    """
    Linearly interpolate times where altitude crosses `level`.

    Returns list of (Time, direction) with direction 'up' or 'down'.
    """
    crossings = []
    for i in range(len(alts) - 1):
        a0, a1 = alts[i] - level, alts[i + 1] - level
        if a0 == 0:
            # Exact hit: infer direction from the next sample when possible.
            if a1 > 0:
                crossings.append((times[i], "up"))
            elif a1 < 0:
                crossings.append((times[i], "down"))
            continue
        if a0 * a1 > 0:
            continue
        if a0 * a1 == 0 and a1 == 0:
            continue
        frac = abs(a0) / (abs(a0) + abs(a1) + 1e-20)
        t_cross = times[i] + frac * (times[i + 1] - times[i])
        crossings.append((t_cross, "up" if a1 > a0 else "down"))
    return crossings


def get_night_times(location: EarthLocation, obs_time: Time) -> Tuple[Time, Time]:
    """
    Return (sunset, sunrise) in UTC for the night beginning on obs_time's date.

    The night runs from geometric sunset (sun altitude crossing 0° downward)
    on the evening of that calendar date through geometric sunrise the next
    morning. This matches observer "night" even when astronomical twilight
    never occurs (e.g. mid-latitude summer).

    If the Sun never sets (polar day), falls back to a 12-hour window centred
    on local solar midnight as a last resort. If the Sun never rises (polar
    night), returns noon→next-noon.
    """
    _configure_iers_for_planning()

    # Search from noon UTC on the evening date through noon the next day.
    date_str = obs_time.iso[:10]
    noon = Time(f"{date_str} 12:00:00")
    times, alts = _altitude_series(get_sun, location, noon, noon + 24 * u.hour, n=577)
    crossings = _find_zero_crossings(times, alts, level=0.0)

    sunset = next((t for t, d in crossings if d == "down"), None)
    sunrise = None
    if sunset is not None:
        sunrise = next((t for t, d in crossings if d == "up" and t > sunset), None)

    if sunset is not None and sunrise is not None and sunrise > sunset:
        return sunset, sunrise

    # Polar night: sun always below horizon across the window.
    if np.all(alts < 0):
        return noon, noon + 24 * u.hour

    # Polar day / no clear night: last-resort evening-centred window (NOT daytime).
    midnight = noon + 12 * u.hour
    return midnight - 6 * u.hour, midnight + 6 * u.hour


def moon_rise_set(location: EarthLocation, night_start: Time, night_end: Time):
    """
    Find moonrise/moonset near the given night.

    Searches a padded window around the night so events just outside sunset/
    sunrise are still reported. Returns (moonrise, moonset) as Time or None.
    """
    _configure_iers_for_planning()

    pad = 6 * u.hour
    times, alts = _altitude_series(
        lambda t: get_body("moon", t),
        location,
        night_start - pad,
        night_end + pad,
        n=721,
    )
    crossings = _find_zero_crossings(times, alts, level=0.0)
    rises = [t for t, d in crossings if d == "up"]
    sets = [t for t, d in crossings if d == "down"]

    moonrise = next((r for r in rises if r <= night_end + pad), None)
    moonset = None
    if moonrise is not None:
        moonset = next((s for s in sets if s > moonrise), None)
    elif sets:
        # Moon already up at window start: report the upcoming set.
        moonset = sets[0]

    return moonrise, moonset


def _moon_altitudes(location: EarthLocation, times: Time) -> np.ndarray:
    """Moon altitude in degrees at each sample time."""
    frame = AltAz(obstime=times, location=location)
    return get_body("moon", times).transform_to(frame).alt.to(u.deg).value


def sun_altitude_deg(time: Time, location: EarthLocation) -> float:
    """Sun altitude in degrees (geometric, no refraction) at a given time/location."""
    _configure_iers_for_planning()
    frame = AltAz(obstime=time, location=location)
    return float(get_sun(time).transform_to(frame).alt.to(u.deg).value)


def moon_separation_deg(ra_deg: float, dec_deg: float, time: Time, location: EarthLocation) -> float:
    """
    Angular separation in degrees between a fixed sky position (ICRS RA/Dec,
    in degrees) and the Moon, as seen from `location` at `time` (topocentric,
    i.e. corrected for the observer's position - the Moon is close enough
    that this matters for a "how close is the Moon" check).

    Both positions are transformed to the same AltAz frame before comparing,
    rather than calling `.separation()` directly across an ICRS (no
    distance - a fixed sky target is conceptually at infinity) vs. GCRS
    (Moon, a real ~384,000 km distance) pair: that mismatched-distance,
    origin-shifting combination has been observed to produce wildly wrong
    separations (tens of degrees) with this astropy version, apparently
    because the "at infinity" ICRS point gets a spurious ~1 AU parallax
    shift applied against the barycentre instead of being treated as
    distance-independent. Comparing within one observer-centred frame
    sidesteps the barycentric origin shift entirely.
    """
    _configure_iers_for_planning()
    frame = AltAz(obstime=time, location=location)
    target = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs").transform_to(frame)
    moon = get_body("moon", time, location=location).transform_to(frame)
    return float(target.separation(moon).to(u.deg).value)


def moon_illumination_pct(time: Time) -> float:
    """
    Approximate Moon illuminated fraction (0-100%) at `time`.

    Derived from the Sun-Moon elongation as seen from Earth's centre, using
    the standard small-body approximation phase_angle ≈ 180° − elongation
    (exact for a Sun at infinite distance; the real Earth-Sun distance makes
    this accurate to well under 1% illumination, adequate for a "is the moon
    too bright" filter - the same tolerance asteroid.py already accepts for
    magnitude/geometry at this pipeline stage). Geocentric, since the
    illuminated fraction barely changes with observer location.
    """
    sun = get_sun(time)
    moon = get_body("moon", time)
    elongation = sun.separation(moon)
    phase_angle = (180.0 * u.deg) - elongation
    illuminated_fraction = (1.0 + np.cos(phase_angle.to(u.rad).value)) / 2.0
    return float(np.clip(illuminated_fraction, 0.0, 1.0) * 100.0)


def transit_altitude_deg(dec_deg: float, lat_deg: float) -> float:
    """Maximum altitude an object ever reaches (at upper transit)."""
    return 90.0 - abs(lat_deg - dec_deg)


def ha_window_visible(ra_deg: float, dec_deg: float, lat_deg: float,
                      lst_mid_deg: float, night_half_h: float,
                      alt_min_deg: float) -> bool:
    """
    Quick test: is the object above alt_min at any moment during the night?

    Uses hour-angle arithmetic to determine whether the window in which the
    object is above alt_min overlaps with the night window (centred on
    local midnight, i.e. `night_half_h` hours either side of `lst_mid_deg`).
    """
    lat = np.radians(lat_deg)
    dec = np.radians(dec_deg)
    alt_min = np.radians(alt_min_deg)

    sin_alt_transit = np.sin(dec) * np.sin(lat) + np.cos(dec) * np.cos(lat)
    if sin_alt_transit < np.sin(alt_min):
        return False

    cos_ha_thresh = (np.sin(alt_min) - np.sin(dec) * np.sin(lat)) / (
        np.cos(dec) * np.cos(lat) + 1e-12
    )

    lst_half_deg = night_half_h * 15.0

    if cos_ha_thresh <= -1.0:
        return True  # circumpolar above alt_min

    if cos_ha_thresh >= 1.0:
        return False  # never reaches alt_min

    ha_thresh_deg = np.degrees(np.arccos(cos_ha_thresh))

    # Angular separation between object RA and LST at midnight
    center_sep = abs(((ra_deg - lst_mid_deg) + 180.0) % 360.0 - 180.0)
    return bool(center_sep < (ha_thresh_deg + lst_half_deg))
