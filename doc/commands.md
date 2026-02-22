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

A basic support for asteroid handling is available.

First, you need to download and load asteroid data from MPC.

```shell
hevelius asteroid download
```

The orbitalal parameters downloaded are cached. You can force redownloading
by using `--force`. Please be gentle on the MPC servers. The data can be loaded
into database if `--load` is specified. The data can optionally be limited
using `--limit LIMIT`, e.g. to load first 10 entries just for testing.

Once the database is loaded, the next step is to show visible asteroids.
Several parameters are mandatory: `--date` that specifies the night date,
and observatory location, using `--lat` and `--lon`. Many for parameters
might be specified to filter list of asteroids. For complete list, see
`bin/hevelius asteroid visible --help`.

An example usage:

```shell
# Visible asteroids on a given night (e.g. mag 10–14, altitude ≥ 25°, numbered < 3000)
hevelius asteroid visible --date 2025-03-15 --lat 52.2 --lon 21.0 --mag-min 10 --mag-max 14 --alt-min 25 --constraint
"number < 3000" --order-by number
```
