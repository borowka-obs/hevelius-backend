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


def _progress(msg: str) -> None:
    """Print progress message to stderr (so stdout stays clean for piping)."""
    print(msg, file=sys.stderr, flush=True)

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
    obs_time = Time(obs_date + " 00:00:00")
    _progress("Fetching asteroid list from database...")
    conn = db.connect()
    cursor = conn.cursor()

    # Build WHERE: magnitude range is applied after computing apparent mag;
    # we pre-filter by absolute magnitude to reduce work
    where_parts = ["absolute_magnitude BETWEEN %s AND %s"]
    params = [mag_min - 5, mag_max + 5]

    if constraint:
        # Sanitize: allow only known columns and numeric/comparison.
        # Quote column names so reserved words (e.g. "number") work in PostgreSQL.
        # Support: "number_lt_10", "number < 10", or split form "number" "<" "10".
        allowed_cols = {"number", "designation", "absolute_magnitude"}
        # Normalize: ASCII spaces and comparison chars (avoid Unicode fullwidth etc.)
        constraint = constraint.strip().replace("\u00a0", " ")
        constraint = constraint.replace("\uff1c", "<").replace("\uff1e", ">").replace("\uff1d", "=")
        op_map = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "=", "ne": "!="}
        sql_ops = ("<", "<=", ">", ">=", "=", "!=")
        added = False

        def apply_constraint(col: str, op: str, val_str: str) -> bool:
            print(f"#### Applying constraint: {col} {op} {val_str}")
            col = col.lower()
            if col not in allowed_cols or op not in sql_ops:
                print(f"#### Invalid constraint: {col}")
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
                print(f"#### where_parts: {where_parts}")
                print(f"#### params: {params}")
                return True
            except ValueError:
                return False

        # Format 1: "number_lt_10" (no spaces)
        alt = re.match(r"^(\w+)_(lt|lte|gt|gte|eq|ne)_(.+)$", constraint, re.IGNORECASE)
        if alt:
            op = op_map.get(alt.group(2).lower())
            if op:
                added = apply_constraint(alt.group(1), op, alt.group(3))

        # Format 2: "number < 10" — regex (space around operator)
        if not added:
            m = re.match(r"^\s*(\w+)\s*(<|<=|>|>=|=|!=)\s*(.+)\s*$", constraint)
            if m:
                added = apply_constraint(m.group(1), m.group(2), m.group(3))

        # Format 3: split by whitespace — "number < 10" -> ["number", "<", "10"]
        if not added:
            tokens = constraint.split()
            if len(tokens) >= 3 and tokens[0].lower() in allowed_cols and tokens[1] in sql_ops:
                added = apply_constraint(tokens[0], tokens[1], tokens[2])

        if constraint and not added:
            _progress(f"  Note: constraint {repr(constraint)} was not applied (use e.g. number_lt_10 or --constraint='number < 10').")

    order_clause = "absolute_magnitude"
    if order_by:
        allowed_order = {"number", "designation", "absolute_magnitude", "semimajor_axis"}
        tokens = order_by.strip().lower().split()
        if tokens and tokens[0] in allowed_order:
            direction = " " + tokens[1] if len(tokens) > 1 and tokens[1] in ("asc", "desc") else ""
            # Quote so reserved words (e.g. "number") work in PostgreSQL
            order_clause = '"' + tokens[0] + '"' + direction

    query = (
        "SELECT number, designation, epoch, mean_anomaly, perihelion_arg, "
        "ascending_node, inclination, eccentricity, mean_motion, "
        "semimajor_axis, absolute_magnitude, slope_parameter "
        "FROM asteroids WHERE " + " AND ".join(where_parts) + " ORDER BY " + order_clause
    )

    print(f"#### query: {query}")
    print(f"#### params: {params}")

    cursor.execute(query, params)
    asteroids = cursor.fetchall()
    conn.close()
    _progress(f"  Found {len(asteroids)} asteroid(s) to check.")

    _progress("Computing night window (sunrise/sunset)...")
    night_start, night_end = _get_night_times(location, obs_time)
    # Sample times during night
    n_samples = 20
    times = night_start + np.linspace(0, (night_end - night_start).to(u.hour).value, n_samples) * u.hour
    _progress(f"  Night: {night_start.iso} to {night_end.iso}")

    visible = []
    _progress("Loading ephemeris and Earth positions...")
    with solar_system_ephemeris.set("builtin"):
        earth_positions = get_body("earth", times)
    _progress("Computing visibility for each asteroid...")

    total = len(asteroids)
    for idx, row in enumerate(asteroids):
        (number, designation, epoch_s, M_epoch, peri, node, inc, e, n, a, H, G) = row
        _progress(f"  [{idx + 1}/{total}] {number or '':>6} {designation}")
        if a is None or a <= 0 or e is None:
            continue
        epoch_jd = _unpack_epoch(epoch_s)
        G = G if G is not None else 0.15

        max_alt = -90.0
        best_mag = 99.0
        best_time = times[0]

        for i, t in enumerate(times):
            x, y, z = _orbit_position_at_jd(
                epoch_jd, float(a), float(e), float(inc), float(node),
                float(peri), float(M_epoch), float(n), t.jd,
            )
            xe, ye, ze = _ecliptic_to_equatorial(x, y, z)
            ep = earth_positions[i]
            ex = ep.cartesian.x.to(u.AU).value
            ey = ep.cartesian.y.to(u.AU).value
            ez = ep.cartesian.z.to(u.AU).value
            ast_geo = (xe - ex, ye - ey, ze - ez)
            r_au = np.sqrt(x * x + y * y + z * z)
            delta_au = np.sqrt(ast_geo[0] ** 2 + ast_geo[1] ** 2 + ast_geo[2] ** 2)
            cos_phase = (x * ast_geo[0] + y * ast_geo[1] + z * ast_geo[2]) / (r_au * delta_au + 1e-20)
            phase_deg = np.degrees(np.arccos(np.clip(cos_phase, -1, 1)))
            mag = _apparent_magnitude(H, G, r_au, delta_au, phase_deg)
            from astropy.coordinates import CartesianRepresentation
            gcrs = GCRS(
                CartesianRepresentation(ast_geo[0] * u.AU, ast_geo[1] * u.AU, ast_geo[2] * u.AU),
                obstime=t,
            )
            altaz = gcrs.transform_to(AltAz(obstime=t, location=location))
            alt_deg = altaz.alt.to(u.deg).value
            if alt_deg > max_alt:
                max_alt = alt_deg
                best_mag = mag
                best_time = t

        if max_alt >= alt_min and mag_min <= best_mag <= mag_max:
            visible.append({
                "number": number,
                "designation": designation,
                "absolute_magnitude": H,
                "apparent_magnitude": round(best_mag, 2),
                "max_altitude_deg": round(max_alt, 2),
                "max_altitude_time": best_time.iso,
            })
    _progress("Done.")
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
