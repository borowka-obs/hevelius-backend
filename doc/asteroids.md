# Asteroid Observation Planning

Hevelius can identify asteroids that are observable from your site on a given
night.  With over one million asteroids in the Minor Planet Center (MPC)
catalogue, the implementation needs to be fast.  This document describes the
data source, the database schema, the CLI, the REST API, and the visibility
algorithm in detail.

## Data source

Orbital elements come from the [MPC MPCORB database](https://minorplanetcenter.net/iau/MPCORB.html).
The full catalogue is distributed as a gzip-compressed fixed-width text file
(`MPCORB.DAT.gz`).  Typical workflow:

```
hevelius asteroid status                 # cache + DB counters
hevelius asteroid download               # fetch MPCORB (skipped if < 7 days old)
hevelius asteroid load                   # upsert into the asteroids table
# or: hevelius asteroid download --load  # download then load
```

The file is cached locally (default: `~/.cache/hevelius/MPCORB.DAT`).  A
download is skipped when that cache is younger than 7 days; use `--force` to
re-download anyway.  The `--limit N` flag on `load` (or `download --load`)
restricts the load to the first *N* records, which is handy for testing.

Permanent MPC numbers are unpacked from the packed designation in columns 1–7
(plain digits, letter-coded forms for 100000–619999, and tilde/base-62 for
≥ 620000). Provisional designations leave `number` NULL.

Proper names come from the MPCORB readable designation field (columns 167–194),
e.g. `(1) Ceres` → `name = Ceres`. Unnamed and provisional objects store NULL.

## Database schema

Orbital elements are stored in the `asteroids` table (migration **22**, with
`name` added in migration **24**):

| Column | Type | Description |
|--------|------|-------------|
| `number` | integer | MPC number (NULL for unnumbered objects) |
| `designation` | varchar(32) | Packed MPC designation (unique key) |
| `name` | varchar(64) | Proper name (NULL if unnamed / provisional) |
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

Indices exist on `absolute_magnitude`, `number`, `designation`, and `lower(name)`.

### Tags (migration 24)

Shared tag vocabulary lives in `asteroid_tags` (`name`, optional `description` /
`color`) with a many-to-many map `asteroid_tag_map`. Any authenticated API user
may create, edit, delete, or attach tags — the vocabulary is deployment-wide,
same pattern as other shared catalogue metadata.

## CLI usage

```
hevelius asteroid status
hevelius asteroid download [--force] [--load] [--limit N]
hevelius asteroid load [--file PATH] [--limit N]
hevelius asteroid show Ceres
hevelius asteroid show 433
hevelius asteroid visible --date 2026-06-15 --lat 52.2 --lon 21.0 \
    --mag-min 8 --mag-max 14 --alt-min 20
```

| Command / option | Default | Description |
|------------------|---------|-------------|
| `status` | — | MPCORB cache location/age and DB asteroid counters |
| `status --count-file` | off | Also count records in the cached MPCORB file |
| `download` | — | Fetch MPCORB; skipped if cache younger than 7 days |
| `download --force` | off | Re-download even if the cache is fresh |
| `download --load` | off | After download, upsert into the DB |
| `load` | — | Upsert asteroids from the cached (or `--file`) MPCORB |
| `show <query>` | — | Detail by proper name, MPC number, or packed designation |
| `show --limit` | 20 | Max candidates listed when the query is ambiguous |
| `show --no-color` | off | Disable ANSI colors |
| `visible --date` | required | Observation date (YYYY-MM-DD) |
| `visible --lat` | required | Observer latitude in degrees |
| `visible --lon` | required | Observer longitude in degrees |
| `visible --alt` | 0 | Observer altitude above sea level (metres) |
| `visible --mag-min` | 8.0 | Minimum apparent magnitude |
| `visible --mag-max` | 16.0 | Maximum apparent magnitude |
| `visible --alt-min` | 20.0 | Minimum altitude above horizon (degrees) |
| `visible --constraint` | — | Extra SQL filter, e.g. `'number < 3000'` |
| `visible --order-by` | absolute\_magnitude | Sort column |

`asteroid show` prefers exact name/number/designation matches. Ambiguous queries
list candidates. When stdout is a TTY, the detail view uses ANSI colors
(disable with `--no-color`).

Progress for `visible` is printed to stderr so stdout output can be redirected
to a file.

## REST API

See `api/openapi.yaml` for the full contract. Summary:

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/asteroids` | Paginated list with filters (name, designation, number, magnitude, tags) |
| GET | `/api/asteroids/{id}` | Detail including attached tags |
| GET | `/api/asteroids/{id}/visibility` | Night altitude/azimuth/magnitude curve from a telescope |
| GET/POST | `/api/asteroid-tags` | List / create tags |
| GET/PATCH/DELETE | `/api/asteroid-tags/{id}` | Tag CRUD |
| POST/DELETE | `/api/asteroids/{id}/tags[/{tag_id}]` | Attach / detach |

All endpoints require JWT (`bearerAuth`).

### Visibility curve semantics

- Default `date` is the **server's local calendar date**, not the telescope site's timezone.
- `visible` is true when max altitude during the night is **above 0°** (geometric horizon only; no airmass or site horizon mask).
- `step_minutes` (1–120, default 10) controls sampling density; smaller steps are more CPU-heavy.

### List performance note

Unfiltered list responses always run `COUNT(*)` on `asteroids`. At full MPCORB
scale that can be expensive; prefer filters when browsing large catalogues.

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
