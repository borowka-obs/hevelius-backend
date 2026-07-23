# Commands documentation

There are two interfaces for the Hevelius system: web and command line.
The command-line can be accessed the following way:

```shell
$ python bin/hevelius --help
usage: hevelius [-h]
                {config,version,db,repo,data,task,catalog,filter,sensor,project,telescope,user,asteroid} ...

positional arguments:
  {config,version,db,repo,data,task,catalog,filter,sensor,project,telescope,user,asteroid}
                        commands
    config              Shows current Hevelius (DB,file repository) configuration.
    version             Shows the current Hevelius version.
    db                  Manages database
    repo                Manages files repository on local storage.
    data                Explores, analyses and digs through available data (data mining)
    task                Task-related commands
    catalog             List catalogs or search catalog objects
    filter              List, add, edit, or set active state of a filter
    sensor              List, add, or edit a sensor (camera)
    project             List, add, edit, show project or manage subframes
    telescope           List, add, edit, show telescope or manage sensor/filters
    user                List, add, enable, or disable a user
    asteroid            Asteroid observation planning (MPC orbits, visibility)

options:
  -h, --help            show this help message and exit
```

Help for specific commands is available, e.g. `python bin/hevelius catalog --help`.

Most entity commands use a singular noun with subcommands. Listing is always
`list`:

```shell
hevelius catalog list
hevelius filter list
hevelius sensor list
hevelius project list
hevelius telescope list
hevelius user list
```

## Task groups

Show clusters of frames that share similar coordinates (useful for finding
large observation sets):

```shell
hevelius task groups
hevelius task groups --min 50
```

## Task search — frames near sky coordinates

`hevelius task search` finds frames (completed tasks) near a sky position.
Use `--object` to resolve the centre from a catalog name, or pass `--ra` /
`--decl` directly. Search radius is `--proximity` (default: 1 degree).

Use `--format` for the frames list output: `none`, `filenames`, `csv`,
`brief`, `full`, or `pixinsight`.

The `pixinsight` format is intended for PixInsight's SubframeSelector. To
import the list, open PixInsight, menu Process → ImageInspection →
SubframeSelector, then click **edit instance source code** (square icon at the
bottom), and paste the content into `P.subframes`.

```shell
python bin/hevelius task search --object C38 --proximity 0.5 --format full
python bin/hevelius task search --ra "05 34 31" --decl "+22 00 52" --format brief
```

```shell
$ python bin/hevelius task search --help
usage: hevelius task search [-h] [-r RA] [-d DECL] [-p PROXIMITY] [-f FORMAT]
                            [-o OBJECT] [-b BIN] [--focal FOCAL]
                            [--resx RESX] [--resy RESY] [--sensor SENSOR]
                            [--sensor-id SENSOR_ID]

options:
  -h, --help            show this help message and exit
  -r, --ra RA           Right Ascension (HH MM [SS] format)
  -d, --decl DECL       Declination of the image searched (+DD MM SS format)
  -p, --proximity PROXIMITY
                        radius of an area to look at (in degrees)
  -f, --format FORMAT   format of the frames list output: none, filenames,
                        csv, brief, full
  -o, --object OBJECT   Resolve centre from catalog object name (instead of
                        --ra/--decl)
  -b, --bin BIN         filtering: binning of the frames to look for (1..4, 0
                        means any)
  --focal FOCAL         filtering: focal length (mm)
  --resx RESX           filtering: X resolution (pixels)
  --resy RESY           filtering: y resolution (pixels)
  --sensor SENSOR       filtering: specifies sensor by its name (name in
                        sensors table)
  --sensor-id SENSOR_ID
                        filtering: specifies sensor by its id (sensor_id in
                        sensors table)
```

## Catalog — list installed catalogs and search objects

```shell
# Installed catalogs with object counts
hevelius catalog list
hevelius catalog list --sort name

# Search objects (all filters optional)
hevelius catalog search M31
hevelius catalog search --catalog NGC --const Cyg
hevelius catalog search --ra "0 42 44" --dec "+41 16 09" --radius 2.0 --limit 5
```

See [catalogs.md](catalogs.md) for full search options and API equivalents.

## Asteroids

Asteroid orbital elements come from the Minor Planet Center (MPCORB). Typical
workflow:

```shell
# Check whether MPCORB was downloaded and whether the DB has asteroids
hevelius asteroid status

# Download MPCORB.DAT (skipped if the local cache is younger than 7 days)
hevelius asteroid download

# Force a re-download regardless of cache age
hevelius asteroid download --force

# Upsert orbital elements from the cached file into the database
hevelius asteroid load

# Or download and load in one step
hevelius asteroid download --load

# Look up one asteroid by proper name, MPC number, or packed designation
hevelius asteroid show Ceres
hevelius asteroid show 433

# Catalogue listing (first 100 by MPC number; filters/sorting available)
hevelius asteroid list
hevelius asteroid list --name cer --limit 20 --sort-by absolute_magnitude

# With a telescope, also print a night altitude chart for that site
hevelius asteroid show Vesta --telescope-id 3
hevelius asteroid show Vesta --telescope hakos-e180 --date 2026-07-22
```

The orbital parameters are cached locally (default: `~/.cache/hevelius/MPCORB.DAT`).
Please be gentle on the MPC servers. Use `--limit N` with `load` (or
`download --load`) to load only the first *N* records for testing.

Once the database is loaded, list visible asteroids. Mandatory parameters are
`--date` (night date) and observatory location (`--lat`, `--lon`). See
`bin/hevelius asteroid visible --help` for the full filter list.

An example usage:

```shell
# Visible asteroids on a given night (e.g. mag 10–14, altitude ≥ 25°, numbered < 3000)
hevelius asteroid visible --date 2025-03-15 --lat 52.2 --lon 21.0 --mag-min 10 --mag-max 14 --alt-min 25 --constraint number_lt_3000 --order-by number
```
