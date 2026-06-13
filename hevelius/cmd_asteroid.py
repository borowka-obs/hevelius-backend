"""
Asteroid observation planning: download MPC orbits, list visible asteroids
for a given night/location with magnitude and altitude filters.
"""

import gzip
import os
import re
import sys
import urllib.request
from typing import List, Optional, Tuple

from astropy.coordinates import (
    AltAz,
    EarthLocation,
    GCRS,
    get_body,
    get_sun,
    solar_system_ephemeris,
)
from astropy.time import Time
from astropy import units as u
import numpy as np

from hevelius import db
from hevelius.config import load_config

# MPCORB.DAT fixed-width columns (0-based); format from MPC Export Format.
# Columns 1-7: designation (1-4 packed, 5-7 number or continuation)
# 9-13: H, 15-19: G, 21-25: Epoch, 27-35: M, 38-46: omega, 49-57: Omega,
# 60-68: i, 71-79: e, 81-91: n, 93-103: a
MPCORB_COLS = {
    "designation": (0, 7),
    "H": (8, 13),
    "G": (14, 19),
    "epoch": (20, 25),
    "M": (26, 35),
    "perihelion_arg": (37, 46),
    "ascending_node": (48, 57),
    "inclination": (59, 68),
    "eccentricity": (70, 79),
    "mean_motion": (80, 91),
    "semimajor_axis": (92, 103),
}

MPCORB_URL = "https://minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz"


def _progress(msg: str) -> None:
    """Print progress message to stderr (so stdout stays clean for piping)."""
    print(msg, file=sys.stderr, flush=True)


def _cache_dir() -> str:
    """Return directory for caching MPC data (e.g. MPCORB.DAT)."""
    config = load_config()
    paths = config.get("paths", {})
    if "asteroid-cache" in paths:
        return paths["asteroid-cache"]
    xdg = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return os.path.join(xdg, "hevelius")


def _cache_path() -> str:
    return os.path.join(_cache_dir(), "MPCORB.DAT")


def _parse_float(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _unpack_epoch(packed: str) -> float:
    """Convert MPC packed epoch (5 chars, e.g. K22A2) to Julian Date (approximate)."""
    packed = packed.strip()
    if len(packed) < 5:
        return 2451545.0  # J2000 fallback
    # Format: IY XX P (year 2 digits, half-month letter, day-in-half letter+digit)
    # Half-months A=Jan1-15, B=Jan16-31, ..., Y=Dec16-31 (skip I)
    half = "ABCDEFGHJKLMNOPQRSTUVWXY"  # 24 half-months
    try:
        yy = int(packed[0:2])
        year = 2000 + yy if yy < 50 else 1900 + yy
        x = packed[2]
        if x not in half:
            return 2451545.0
        half_idx = half.index(x)
        month = (half_idx // 2) + 1
        day_off = (half_idx % 2) * 15
        day_char = packed[3] if len(packed) > 3 else "0"
        day_digit = packed[4] if len(packed) > 4 else "0"
        if day_char.isalpha():
            day = ord(day_char.upper()) - ord("A") + 10
        else:
            day = int(day_char) if day_char.isdigit() else 0
        day += day_off
        frac = int(day_digit) / 10.0 if day_digit.isdigit() else 0.0
        day += frac
        t = Time(f"{year}-{month:02d}-{day:02d}", format="iso", scale="tt")
        return t.jd
    except (ValueError, IndexError):
        return 2451545.0


def _parse_mpcorb_line(line: str) -> Optional[dict]:
    """Parse one line of MPCORB.DAT; return dict of fields or None if invalid."""
    if len(line) < 104:
        return None
    try:
        designation = line[MPCORB_COLS["designation"][0]: MPCORB_COLS["designation"][1]].strip()
        if not designation or designation.startswith("--------"):
            return None
        number = _parse_int(line[4:7])  # columns 5-7 are number for numbered
        H = _parse_float(line[MPCORB_COLS["H"][0]: MPCORB_COLS["H"][1]])
        G = _parse_float(line[MPCORB_COLS["G"][0]: MPCORB_COLS["G"][1]])
        epoch = line[MPCORB_COLS["epoch"][0]: MPCORB_COLS["epoch"][1]].strip()
        M = _parse_float(line[MPCORB_COLS["M"][0]: MPCORB_COLS["M"][1]])
        peri = _parse_float(line[MPCORB_COLS["perihelion_arg"][0]: MPCORB_COLS["perihelion_arg"][1]])
        node = _parse_float(line[MPCORB_COLS["ascending_node"][0]: MPCORB_COLS["ascending_node"][1]])
        inc = _parse_float(line[MPCORB_COLS["inclination"][0]: MPCORB_COLS["inclination"][1]])
        e = _parse_float(line[MPCORB_COLS["eccentricity"][0]: MPCORB_COLS["eccentricity"][1]])
        n = _parse_float(line[MPCORB_COLS["mean_motion"][0]: MPCORB_COLS["mean_motion"][1]])
        a = _parse_float(line[MPCORB_COLS["semimajor_axis"][0]: MPCORB_COLS["semimajor_axis"][1]])
        if M is None or peri is None or node is None or inc is None or e is None or n is None or a is None:
            return None
        return {
            "number": number,
            "designation": designation[:32],
            "epoch": epoch[:16],
            "mean_anomaly": M,
            "perihelion_arg": peri,
            "ascending_node": node,
            "inclination": inc,
            "eccentricity": e,
            "mean_motion": n,
            "semimajor_axis": a,
            "absolute_magnitude": H,
            "slope_parameter": G if G is not None else 0.15,
        }
    except (ValueError, IndexError):
        return None


def download_mpcorb(force: bool = False) -> str:
    """
    Download MPCORB.DAT.gz from MPC to local cache. Returns path to cached file
    (gunzipped as MPCORB.DAT).
    """
    cache_dir = _cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    out_path = _cache_path()
    if not force and os.path.isfile(out_path):
        return out_path
    gz_path = out_path + ".gz"
    print(f"Downloading {MPCORB_URL} ...")
    urllib.request.urlretrieve(MPCORB_URL, gz_path)
    with gzip.open(gz_path, "rb") as f_in:
        with open(out_path, "wb") as f_out:
            f_out.write(f_in.read())
    try:
        os.remove(gz_path)
    except OSError:
        # Best-effort cleanup: ignore failure to remove temporary .gz file.
        pass
    print(f"Cached to {out_path}")
    return out_path


def _count_mpcorb_lines(path: str) -> int:
    """Count lines in MPCORB file that look like asteroid records (approximate)."""
    count = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if len(line) >= 104 and not line.strip().startswith("--------"):
                count += 1
    return count


def _asteroid_count_db(conn) -> int:
    """Return number of rows in asteroids table."""
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM asteroids")
    out = cursor.fetchone()[0]
    cursor.close()
    return out


def load_mpcorb_into_db(conn, path: Optional[str] = None, limit: Optional[int] = None) -> int:
    """
    Parse cached MPCORB.DAT and upsert into asteroids table.
    Returns number of rows inserted/updated.
    """
    if path is None:
        path = _cache_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"MPCORB not found at {path}. Run download first.")

    print("Counting asteroid records in file (one-time pass)...")
    file_count = _count_mpcorb_lines(path)
    db_count_before = _asteroid_count_db(conn)
    total_to_process = min(file_count, limit) if limit else file_count
    print(f"  MPCORB file: ~{file_count} asteroid records. DB currently: {db_count_before} asteroids.")
    print(f"  Loading up to {total_to_process} records...")
    print()

    count = 0
    progress_interval = max(1, min(50_000, total_to_process // 20))  # ~20 updates or every 50k
    cursor = conn.cursor()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                row = _parse_mpcorb_line(line)
                if row is None:
                    continue
                cursor.execute(
                    """
                    INSERT INTO asteroids (
                        number, designation, epoch, mean_anomaly, perihelion_arg,
                        ascending_node, inclination, eccentricity, mean_motion,
                        semimajor_axis, absolute_magnitude, slope_parameter
                    ) VALUES (
                        %(number)s, %(designation)s, %(epoch)s, %(mean_anomaly)s,
                        %(perihelion_arg)s, %(ascending_node)s, %(inclination)s,
                        %(eccentricity)s, %(mean_motion)s, %(semimajor_axis)s,
                        %(absolute_magnitude)s, %(slope_parameter)s
                    )
                    ON CONFLICT (designation) DO UPDATE SET
                        number = EXCLUDED.number,
                        epoch = EXCLUDED.epoch,
                        mean_anomaly = EXCLUDED.mean_anomaly,
                        perihelion_arg = EXCLUDED.perihelion_arg,
                        ascending_node = EXCLUDED.ascending_node,
                        inclination = EXCLUDED.inclination,
                        eccentricity = EXCLUDED.eccentricity,
                        mean_motion = EXCLUDED.mean_motion,
                        semimajor_axis = EXCLUDED.semimajor_axis,
                        absolute_magnitude = EXCLUDED.absolute_magnitude,
                        slope_parameter = EXCLUDED.slope_parameter
                    """,
                    row,
                )
                count += 1
                if count % progress_interval == 0 or count == total_to_process:
                    conn.commit()
                    pct = 100.0 * count / total_to_process if total_to_process else 0
                    print(f"  Loaded {count:,} / {total_to_process:,} ({pct:.1f}%)")
                elif count % 1000 == 0:
                    conn.commit()  # periodic commit between progress prints
                if limit and count >= limit:
                    break
    finally:
        conn.commit()
        cursor.close()

    db_count_after = _asteroid_count_db(conn)
    print()
    print(f"Load complete. Processed {count:,} records. DB now: {db_count_after:,} asteroids.")
    return count


def _kepler_M_to_E(M_deg: float, e: float) -> float:
    """Solve Kepler equation M = E - e*sin(E) for E (radians)."""
    M = np.radians(M_deg)
    E = M
    for _ in range(30):
        d = E - e * np.sin(E) - M
        if abs(d) < 1e-10:
            break
        E -= d / (1 - e * np.cos(E))
    return E


def _orbit_position_at_jd(
    epoch_jd: float,
    a_au: float,
    e: float,
    inc_deg: float,
    node_deg: float,
    peri_deg: float,
    M_epoch_deg: float,
    n_deg_per_day: float,
    jd: float,
) -> Tuple[float, float, float]:
    """
    Heliocentric ecliptic position (x,y,z) in AU at time jd.
    Elements: a (AU), e, i, Omega, omega, M at epoch, n (deg/day).
    """
    dt = jd - epoch_jd
    M = M_epoch_deg + n_deg_per_day * dt
    M = M % 360.0
    E = _kepler_M_to_E(M, e)
    # True anomaly
    nu = 2 * np.arctan2(np.sqrt(1 + e) * np.sin(E / 2), np.sqrt(1 - e) * np.cos(E / 2))
    r = a_au * (1 - e * np.cos(E))
    # Position in orbital plane
    x_orb = r * np.cos(nu)
    y_orb = r * np.sin(nu)
    # Rotate to ecliptic: Rz(-Omega) Rx(-i) Rz(-omega)
    inc = np.radians(inc_deg)
    node = np.radians(node_deg)
    peri = np.radians(peri_deg)
    cos_o = np.cos(peri)
    sin_o = np.sin(peri)
    cos_O = np.cos(node)
    sin_O = np.sin(node)
    cos_i = np.cos(inc)
    sin_i = np.sin(inc)
    x = (cos_O * cos_o - sin_O * sin_o * cos_i) * x_orb + (-cos_O * sin_o - sin_O * cos_o * cos_i) * y_orb
    y = (sin_O * cos_o + cos_O * sin_o * cos_i) * x_orb + (-sin_O * sin_o + cos_O * cos_o * cos_i) * y_orb
    z = sin_o * sin_i * x_orb + cos_o * sin_i * y_orb
    return (x, y, z)


def _ecliptic_to_equatorial(xe, ye, ze):
    """Ecliptic (J2000) to equatorial (same origin). Obliquity ~23.44 deg."""
    eps = np.radians(23.4392911)
    x = xe
    y = ye * np.cos(eps) - ze * np.sin(eps)
    z = ye * np.sin(eps) + ze * np.cos(eps)
    return (x, y, z)


def _apparent_magnitude(H: float, G: float, r_au: float, delta_au: float, phase_deg: float) -> float:
    """Apparent magnitude from H, G (phase slope), r (helio dist), delta (obs dist), phase angle."""
    if H is None or r_au <= 0 or delta_au <= 0:
        return 99.0
    phi1 = np.exp(-3.33 * np.tan(np.radians(phase_deg) / 2) ** 0.63)
    phi2 = np.exp(-1.87 * np.tan(np.radians(phase_deg) / 2) ** 1.22)
    phi = (1 - G) * phi1 + G * phi2
    return H + 5 * np.log10(r_au * delta_au) - 2.5 * np.log10(phi)


def _get_night_times(location: EarthLocation, obs_time: Time) -> Tuple[Time, Time]:
    """Return (start, end) of night in UTC (sun 18 deg below horizon)."""
    from astropy.coordinates import AltAz
    midnight = obs_time + 0.5 * u.day
    times = midnight + np.linspace(-12, 12, 200) * u.hour
    frame = AltAz(obstime=times, location=location)
    sun = get_sun(times)
    sun_altaz = sun.transform_to(frame)
    below = np.where(sun_altaz.alt < -18 * u.deg)[0]
    if len(below) == 0:
        return midnight - 6 * u.hour, midnight + 6 * u.hour
    start_idx = below[0]
    end_idx = below[-1]
    return times[start_idx], times[end_idx]


def _xyz_to_radec(x: float, y: float, z: float) -> Tuple[float, float]:
    """Convert equatorial Cartesian to RA/Dec in degrees."""
    r = np.sqrt(x * x + y * y + z * z)
    if r < 1e-20:
        return 0.0, 0.0
    dec = np.degrees(np.arcsin(np.clip(z / r, -1.0, 1.0)))
    ra = np.degrees(np.arctan2(y, x)) % 360.0
    return ra, dec


def _transit_altitude(dec_deg: float, lat_deg: float) -> float:
    """Maximum altitude an object ever reaches (at upper transit)."""
    return 90.0 - abs(lat_deg - dec_deg)


def _night_visible(ra_deg: float, dec_deg: float, lat_deg: float,
                   lst_mid_deg: float, night_half_hours: float,
                   alt_min_deg: float) -> bool:
    """
    Quick test: is the object above alt_min at any moment during the night?

    Uses hour-angle arithmetic to determine whether the window in which the
    object is above alt_min overlaps with the night window (centred on midnight).
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

    lst_half_deg = night_half_hours * 15.0

    if cos_ha_thresh <= -1.0:
        return True  # circumpolar above alt_min

    if cos_ha_thresh >= 1.0:
        return False  # never reaches alt_min

    ha_thresh_deg = np.degrees(np.arccos(cos_ha_thresh))

    # Angular separation between object RA and LST at midnight
    center_sep = abs(((ra_deg - lst_mid_deg) + 180.0) % 360.0 - 180.0)
    return center_sep < (ha_thresh_deg + lst_half_deg)


def compute_visibility(
    location: EarthLocation,
    obs_date: str,
    mag_min: float = 8.0,
    mag_max: float = 16.0,
    alt_min: float = 20.0,
    constraint: Optional[str] = None,
    order_by: Optional[str] = None,
) -> List[dict]:
    """
    Compute asteroid visibility for given location and date.

    Uses a staged approach to handle 1M+ asteroids efficiently:
      1. DB query pre-filters by absolute magnitude (cheap SQL index).
      2. Per asteroid: compute position at astronomical midnight (one Kepler solve).
      3. Quick geometric checks eliminate most asteroids without expensive transforms:
         a. Transit altitude < alt_min  → skip.
         b. Night hour-angle window check → skip if object never above alt_min at night.
         c. Apparent magnitude at midnight outside [mag_min, mag_max] → skip.
      4. Survivors get a precise AltAz transform to confirm altitude and find best time.

    Args:
        location: Observer location
        obs_date: Observation date (YYYY-MM-DD)
        mag_min: Minimum apparent magnitude filter
        mag_max: Maximum apparent magnitude filter
        alt_min: Minimum altitude filter (degrees) for max altitude during night
        constraint: Optional SQL fragment to limit selection (e.g. "number < 3000").
                    Only column names number, designation, absolute_magnitude are allowed.
        order_by: Optional ORDER BY clause (e.g. "absolute_magnitude", "number").
                  Default is absolute_magnitude.

    Returns:
        List of visible asteroids with designation, magnitude, max_altitude, etc.
    """
    from astropy.coordinates import CartesianRepresentation

    obs_time = Time(obs_date + " 00:00:00")

    _progress("Computing night window...")
    night_start, night_end = _get_night_times(location, obs_time)
    night_duration_h = (night_end - night_start).to(u.hour).value
    night_half_h = night_duration_h / 2.0
    t_midnight = night_start + night_half_h * u.hour
    _progress(f"  Night: {night_start.iso} to {night_end.iso} (midnight {t_midnight.iso})")

    lat_deg = location.lat.deg
    lst_midnight_deg = t_midnight.sidereal_time("apparent", longitude=location.lon).deg

    _progress("Computing Earth position at midnight...")
    with solar_system_ephemeris.set("builtin"):
        earth_mid = get_body("earth", t_midnight)
    ex_mid = earth_mid.cartesian.x.to(u.AU).value
    ey_mid = earth_mid.cartesian.y.to(u.AU).value
    ez_mid = earth_mid.cartesian.z.to(u.AU).value

    _progress("Querying asteroids from database...")
    conn = db.connect()
    cursor = conn.cursor()

    # Pre-filter by absolute magnitude. Main-belt asteroids are ~2-3 AU away,
    # adding ~4-5 mag; allow a generous margin of 7 mag for closer/farther objects.
    H_margin = 7.0
    where_parts = ["absolute_magnitude IS NOT NULL", "absolute_magnitude <= %s"]
    params: list = [mag_max + H_margin]

    if constraint:
        allowed_cols = {"number", "designation", "absolute_magnitude"}
        constraint = constraint.strip()
        op_map = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "=", "ne": "!="}
        sql_ops = ("<", "<=", ">", ">=", "=", "!=")
        added = False

        def apply_constraint(col: str, op: str, val_str: str) -> bool:
            col = col.lower()
            if col not in allowed_cols or op not in sql_ops:
                return False
            col_ident = '"' + col + '"'
            if col == "designation":
                where_parts.append(col_ident + " " + op + " %s")
                params.append(val_str.strip())
                return True
            try:
                v = int(val_str.strip()) if col == "number" else float(val_str.strip())
                where_parts.append(col_ident + " " + op + " %s")
                params.append(v)
                return True
            except ValueError:
                return False

        alt_m = re.match(r"^(\w+)_(lt|lte|gt|gte|eq|ne)_(.+)$", constraint, re.IGNORECASE)
        if alt_m:
            op = op_map.get(alt_m.group(2).lower())
            if op:
                added = apply_constraint(alt_m.group(1), op, alt_m.group(3))
        if not added:
            m = re.match(r"^\s*(\w+)\s*(<|<=|>|>=|=|!=)\s*(.+)\s*$", constraint)
            if m:
                added = apply_constraint(m.group(1), m.group(2), m.group(3))
        if not added:
            tokens = constraint.split()
            if len(tokens) >= 3 and tokens[0].lower() in allowed_cols and tokens[1] in sql_ops:
                added = apply_constraint(tokens[0], tokens[1], tokens[2])
        if constraint and not added:
            _progress(f"  Note: constraint {repr(constraint)} not applied.")

    order_clause = "absolute_magnitude"
    if order_by:
        allowed_order = {"number", "designation", "absolute_magnitude", "semimajor_axis"}
        tokens = order_by.strip().lower().split()
        if tokens and tokens[0] in allowed_order:
            direction = " " + tokens[1] if len(tokens) > 1 and tokens[1] in ("asc", "desc") else ""
            order_clause = '"' + tokens[0] + '"' + direction

    query = (
        "SELECT number, designation, epoch, mean_anomaly, perihelion_arg, "
        "ascending_node, inclination, eccentricity, mean_motion, "
        "semimajor_axis, absolute_magnitude, slope_parameter "
        "FROM asteroids WHERE " + " AND ".join(where_parts) + " ORDER BY " + order_clause
    )
    cursor.execute(query, params)

    BATCH = 10_000
    PROGRESS_EVERY = 50_000

    visible = []
    total_checked = 0
    skipped_altitude = 0
    skipped_night = 0
    skipped_magnitude = 0

    _progress("Screening asteroids (position at midnight)...")

    while True:
        rows = cursor.fetchmany(BATCH)
        if not rows:
            break

        for row in rows:
            (number, designation, epoch_s, M_epoch, peri, node, inc, e, n, a, H, G) = row
            total_checked += 1

            if total_checked % PROGRESS_EVERY == 0:
                _progress(
                    f"  Checked {total_checked:,} | visible so far: {len(visible)} "
                    f"| rejected: alt={skipped_altitude:,} night={skipped_night:,} mag={skipped_magnitude:,}"
                )

            if a is None or a <= 0 or e is None or e >= 1.0:
                skipped_altitude += 1
                continue

            G_val = G if G is not None else 0.15
            epoch_jd = _unpack_epoch(epoch_s)

            # Compute heliocentric position at midnight (one Kepler solve)
            x, y, z = _orbit_position_at_jd(
                epoch_jd, float(a), float(e), float(inc), float(node),
                float(peri), float(M_epoch), float(n), t_midnight.jd,
            )
            xe, ye, ze = _ecliptic_to_equatorial(x, y, z)
            ast_geo = (xe - ex_mid, ye - ey_mid, ze - ez_mid)
            r_au = np.sqrt(x * x + y * y + z * z)
            delta_au = np.sqrt(ast_geo[0] ** 2 + ast_geo[1] ** 2 + ast_geo[2] ** 2)

            # Quick check a: transit altitude
            ra_deg, dec_deg = _xyz_to_radec(ast_geo[0], ast_geo[1], ast_geo[2])
            if _transit_altitude(dec_deg, lat_deg) < alt_min:
                skipped_altitude += 1
                continue

            # Quick check b: night hour-angle overlap
            if not _night_visible(ra_deg, dec_deg, lat_deg, lst_midnight_deg, night_half_h, alt_min):
                skipped_night += 1
                continue

            # Quick check c: apparent magnitude at midnight
            cos_phase = (x * ast_geo[0] + y * ast_geo[1] + z * ast_geo[2]) / (r_au * delta_au + 1e-20)
            phase_deg = np.degrees(np.arccos(np.clip(cos_phase, -1, 1)))
            mag = _apparent_magnitude(H, G_val, r_au, delta_au, phase_deg)
            if mag < mag_min or mag > mag_max:
                skipped_magnitude += 1
                continue

            # Precise AltAz at midnight
            gcrs = GCRS(
                CartesianRepresentation(ast_geo[0] * u.AU, ast_geo[1] * u.AU, ast_geo[2] * u.AU),
                obstime=t_midnight,
            )
            altaz = gcrs.transform_to(AltAz(obstime=t_midnight, location=location))
            alt_deg = altaz.alt.to(u.deg).value
            best_time = t_midnight

            if alt_deg < alt_min:
                # Midnight is not the peak; try the transit moment if it falls within the night
                ha_mid = ((lst_midnight_deg - ra_deg) + 180.0) % 360.0 - 180.0
                transit_offset_h = -ha_mid / 15.0
                if abs(transit_offset_h) <= night_half_h:
                    t_transit = t_midnight + transit_offset_h * u.hour
                    with solar_system_ephemeris.set("builtin"):
                        earth_tr = get_body("earth", t_transit)
                    x_tr, y_tr, z_tr = _orbit_position_at_jd(
                        epoch_jd, float(a), float(e), float(inc), float(node),
                        float(peri), float(M_epoch), float(n), t_transit.jd,
                    )
                    xe_tr, ye_tr, ze_tr = _ecliptic_to_equatorial(x_tr, y_tr, z_tr)
                    ast_geo_tr = (
                        xe_tr - earth_tr.cartesian.x.to(u.AU).value,
                        ye_tr - earth_tr.cartesian.y.to(u.AU).value,
                        ze_tr - earth_tr.cartesian.z.to(u.AU).value,
                    )
                    gcrs_tr = GCRS(
                        CartesianRepresentation(
                            ast_geo_tr[0] * u.AU, ast_geo_tr[1] * u.AU, ast_geo_tr[2] * u.AU
                        ),
                        obstime=t_transit,
                    )
                    altaz_tr = gcrs_tr.transform_to(AltAz(obstime=t_transit, location=location))
                    alt_transit = altaz_tr.alt.to(u.deg).value
                    if alt_transit > alt_deg:
                        alt_deg = alt_transit
                        best_time = t_transit
                        r_tr = np.sqrt(x_tr ** 2 + y_tr ** 2 + z_tr ** 2)
                        d_tr = np.sqrt(sum(c ** 2 for c in ast_geo_tr))
                        cp = (x_tr * ast_geo_tr[0] + y_tr * ast_geo_tr[1] + z_tr * ast_geo_tr[2]) / (
                            r_tr * d_tr + 1e-20
                        )
                        mag = _apparent_magnitude(H, G_val, r_tr, d_tr, np.degrees(np.arccos(np.clip(cp, -1, 1))))

                if alt_deg < alt_min:
                    skipped_altitude += 1
                    continue

            if mag < mag_min or mag > mag_max:
                skipped_magnitude += 1
                continue

            visible.append({
                "number": number,
                "designation": designation,
                "absolute_magnitude": H,
                "apparent_magnitude": round(mag, 2),
                "max_altitude_deg": round(alt_deg, 2),
                "max_altitude_time": best_time.iso,
            })

    cursor.close()
    conn.close()

    _progress(
        f"Done. Checked {total_checked:,} | "
        f"rejected: altitude={skipped_altitude:,}, night={skipped_night:,}, magnitude={skipped_magnitude:,} | "
        f"visible: {len(visible)}"
    )
    return visible


def asteroids_download(args):
    """CLI: download and optionally load MPCORB into DB."""
    path = download_mpcorb(force=args.force)
    if args.load:
        conn = db.connect()
        n = load_mpcorb_into_db(conn, path=path, limit=args.limit)
        conn.close()
        print(f"Loaded {n} asteroids into database.")


def asteroids_visible(args):
    """CLI: list visible asteroids for date/location with filters."""
    from astropy.coordinates import EarthLocation
    lat = float(args.lat)
    lon = float(args.lon)
    alt = float(args.alt) if args.alt else 0.0
    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt * u.m)
    results = compute_visibility(
        location,
        args.date,
        mag_min=float(args.mag_min),
        mag_max=float(args.mag_max),
        alt_min=float(args.alt_min),
        constraint=args.constraint or None,
        order_by=args.order_by or None,
    )
    print(f"Found {len(results)} visible asteroid(s)")
    for r in results:
        num = r["number"] or ""
        print(f"  {num:>6} {r['designation']:<12} mag={r['apparent_magnitude']:.2f} "
              f"max_alt={r['max_altitude_deg']:.1f}° at {r['max_altitude_time']}")
    return len(results)
