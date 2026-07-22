# Commands documentation

There are two interfaces for the Hevelius system: web and command line.
The command-line can be accessed the following way:

```shell
$ python bin/hevelius
Hevelius

usage: hevelius [-h] {stats,migrate,version,config,backup,repo,distrib,groups,catalog} ...

positional arguments:
  {stats,migrate,version,config,backup,repo,distrib,groups,catalog}
                        commands
    stats               Show database statistics
    migrate             Migrate to the latest DB schema
    version             Shows the current DB schema version.
    config              Shows current DB configuration.
    backup              Generates DB backup.
    repo                Manages files repository on local storage.
    distrib             Shows photos distribution
    groups              Shows frames' groups
    catalog             Finds astronomical objects in a catalog

options:
  -h, --help            show this help message and exit
```

Help for specific commands is available, e.g.

```shell
$ python bin/hevelius catalog --help
Hevelius

usage: hevelius catalog [-h] [-r RA] [-d DECL] [-p PROXIMITY] [-f FORMAT] [-o OBJECT]

options:
  -h, --help            show this help message and exit
  -r RA, --ra RA        Right Ascension (HH MM [SS] format)
  -d DECL, --decl DECL  Declination of the image searched (+DD MM SS format)
  -p PROXIMITY, --proximity PROXIMITY
                        radius of an area to look at (in degrees)
  -f FORMAT, --format FORMAT
                        format of the frames list output: none, filenames, csv, brief, full
  -o OBJECT, --object OBJECT
                        catalog object to look for
```

## Catalog - searching for catalog objects and associated frames

There are two ways how objects can be located. First is by using a name from the
catalog: `--object M1`. If the object is found, its coordinates are then used.
The alternative way is to specify the coordinates directly:
`--ra "11 22 33" --decl "-22 33 44"`. In both cases, you can specify the radius
around the specified object: `--proximity 2.0`. The default being 1 degree.

Hevelius will find catalog objects for you and also list frames that are in the
database. You can use `--format XXX` to specify the output format. See `--help`
for details as the formats are being updated frequently. As of time of writing
this text, the following formats were supported: `none`, `filenames`, `csv`,
`brief`, `full`, `pixinsight`.

The `pixinsight` format is intended to be used with PixInsight's
SubframeSelector. To import the list, open PixInsight, menu Process ->
ImageInspection -> SubframeSelector, then click on the `edit instance source code`
(square icon at the bottom), then paste the content into `P.subframes`.

An example command line call:

```shell
python bin/hevelius catalog --object C38 --proximity 0.5 --format full
```

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
