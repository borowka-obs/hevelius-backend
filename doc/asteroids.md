# Asteroid Observation Planning

Hevelius can identify asteroids that are observable from your site on a given
night.  With over one million asteroids in the Minor Planet Center (MPC)
catalogue, the implementation needs to be fast.  This document describes the
data source, the database schema, the CLI, and the visibility algorithm in detail.

## Data source

Orbital elements come from the [MPC MPCORB database](https://minorplanetcenter.net/iau/MPCORB.html).
The full catalogue is distributed as a gzip-compressed fixed-width text file
(`MPCORB.DAT.gz`).  Download and load it with:

```
hevelius asteroid download --load
```

The file is cached locally (default: `~/.cache/hevelius/MPCORB.DAT`).  To
force a re-download use `--force`.  The `--limit N` flag restricts the load to
the first *N* records, which is handy for testing.

## Database schema

Orbital elements are stored in the `asteroids` table (migration 15):

| Column | Type | Description |
|--------|------|-------------|
| `number` | integer | MPC number (NULL for unnumbered objects) |
| `designation` | varchar(32) | Packed MPC designation (unique key) |
| `epoch` | varchar(16) | Epoch in MPC packed format |
| `mean_anomaly` | double | Mean anomaly M at epoch (degrees) |
| `perihelion_arg` | double | Argument of perihelion ω (degrees) |
| `ascending_node` | double | Longitude of ascending node Ω (degrees) |
| `inclination` | double | Orbital inclination i (degrees) |
| `eccentricity` | double | Eccentricity e |
| `mean_motion` | double | Mean daily motion n (degrees/day) |
| `semimajor_axis` | double | Semi-major axis a (AU) |
| `absolute_magnitude` | double | Absolute magnitude H |
| `slope_parameter` | double | Phase slope parameter G (default 0.15) |

Indices exist on `absolute_magnitude`, `number`, and `designation`.

## CLI usage

```
hevelius asteroid visible --date 2026-06-15 --lat 52.2 --lon 21.0 \
    --mag-min 8 --mag-max 14 --alt-min 20
```

| Option | Default | Description |
|--------|---------|-------------|
| `--date` | required | Observation date (YYYY-MM-DD) |
| `--lat` | required | Observer latitude in degrees |
| `--lon` | required | Observer longitude in degrees |
| `--alt` | 0 | Observer altitude above sea level (metres) |
| `--mag-min` | 8.0 | Minimum apparent magnitude |
| `--mag-max` | 16.0 | Maximum apparent magnitude |
| `--alt-min` | 20.0 | Minimum altitude above horizon (degrees) |
| `--constraint` | — | Extra SQL filter, e.g. `'number < 3000'` |
| `--order-by` | absolute\_magnitude | Sort column |

Progress is printed to stderr so stdout output can be redirected to a file.

## Visibility algorithm

### Design goals

* Handle ≥ 1 million asteroids without running out of memory or taking hours.
* Apply cheap discriminators first; use expensive ones only for survivors.
* Provide live progress feedback.

### Stage 1 — Database pre-filter (absolute magnitude)

The SQL query restricts candidates to asteroids whose absolute magnitude H
satisfies:

```
H ≤ mag_max + 7
```

The constant 7 mag is a generous upper bound on the distance modulus for
main-belt objects (typically 2–3 AU from both the Sun and the observer, giving
`5 log10(r·Δ) ≈ 4–5 mag`).  Objects far outside this range cannot possibly
appear bright enough, so they are discarded cheaply via the indexed
`absolute_magnitude` column before any orbital mechanics are computed.

Results are streamed from the database in batches of 10,000 rows to keep
memory usage flat regardless of catalogue size.

### Stage 2 — Orbital position at midnight (one Kepler solve)

For each surviving asteroid the heliocentric position is computed for a single
moment: **astronomical midnight** (the midpoint of the night, defined by the
sun being at least 18° below the horizon).

The computation follows standard two-body orbital mechanics:

1. Advance the mean anomaly from the epoch: `M = M₀ + n·Δt`
2. Solve Kepler's equation `M = E − e sin E` iteratively (Newton–Raphson,
   converges in ≈ 5 iterations to 10⁻¹⁰ rad).
3. Compute the true anomaly ν and heliocentric distance r.
4. Rotate from the orbital plane to the ecliptic (J2000) via the standard
   Euler-angle sequence: Rz(−Ω) Rx(−i) Rz(−ω).
5. Convert ecliptic coordinates to equatorial (J2000) using the obliquity
   ε = 23.4393°.

The geocentric vector is obtained by subtracting the Earth's position (from
the built-in astropy ephemeris) from the heliocentric vector.

### Stage 3a — Transit altitude check (trig, no transform)

From the geocentric equatorial vector the RA and Dec are computed.  The
**upper transit altitude** (maximum altitude the object ever reaches) is:

```
alt_max = 90° − |lat − dec|
```

If `alt_max < alt_min` the asteroid never rises high enough from this site
and is discarded immediately.  This single subtraction and comparison
eliminates a large fraction of objects for mid-latitude observers (objects
near the celestial pole or near the horizon always fail here).

### Stage 3b — Night hour-angle overlap check (arithmetic, no transform)

This check answers: *"Does the object spend any time above `alt_min` during
the night?"*

The altitude as a function of hour angle (HA) is:

```
sin(alt) = sin(dec)·sin(lat) + cos(dec)·cos(lat)·cos(HA)
```

Setting `alt = alt_min` gives the threshold hour angle:

```
cos(HA_thresh) = (sin(alt_min) − sin(dec)·sin(lat)) / (cos(dec)·cos(lat))
```

* If `cos(HA_thresh) ≤ −1`: the object is **always** above `alt_min`
  (circumpolar above threshold) — keep it.
* If `cos(HA_thresh) ≥ 1`: the object **never** reaches `alt_min` — discard.
* Otherwise: the object is above `alt_min` for `|HA| < HA_thresh`, i.e. when
  the Local Sidereal Time (LST) is within `(RA − HA_thresh°, RA + HA_thresh°)`.

The night window in LST is centred on the midnight LST with a half-width of
`night_duration / 2 × 15 deg/h`.  A simple angular-distance comparison on
the circle checks whether the two windows overlap.

This eliminates objects that transit during the day (wrong side of the sky)
without any coordinate-frame transformation.

### Stage 3c — Apparent magnitude check

The apparent magnitude at midnight is computed using the HG photometric model:

```
V = H + 5 log10(r·Δ) − 2.5 log10((1−G)·Φ₁ + G·Φ₂)
```

where Φ₁ and Φ₂ are the Bowell phase functions and the phase angle is derived
from the heliocentric and geocentric vectors already in hand.  Objects whose
magnitude falls outside `[mag_min, mag_max]` are discarded.

### Stage 4 — Precise AltAz transform (survivors only)

For the small fraction that passes all three pre-filters, a full
`GCRS → AltAz` coordinate transform (via astropy) is performed at midnight to
obtain an accurate altitude.

**Transit refinement:** if the altitude at midnight is below `alt_min` (the
object is above the threshold at some other point in the night), the transit
time is estimated from the current LST and RA, a second Kepler solve is
performed for that moment, and the precise altitude at transit is computed.
Only if the altitude still fails the threshold is the object rejected.

### Performance characteristics

| Stage | Cost per asteroid | Typical rejection rate |
|-------|------------------|----------------------|
| SQL H filter | negligible (index) | ~50–80 % of catalogue |
| Transit altitude | 1 subtraction | ~20–40 % of remainder |
| Night HA overlap | ~10 trig ops | ~30–60 % of remainder |
| Magnitude | ~5 trig ops | ~50–90 % of remainder |
| Precise AltAz | full transform | applied to survivors only |

In practice fewer than 0.1 % of catalogue objects reach stage 4, making the
full scan feasible in minutes even on a single CPU core.
