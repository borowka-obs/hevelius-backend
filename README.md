# hevelius-backend

This is a backend interface for Hevelius, an astronomy processing software and
observatory management system. It's in the early stages of development, but some
of the features are usable already.

## Current capabilities

Status as of Jan 2025:

- **Scan FITS repository on disk**: Hevelius is able to scan a local disk for FITS files, extract some data from found files
  (from filenames and FITS header) and put this information into PostgreSQL DB. Then the DB is used to report various
  characteristics.
- **Full sky histogram**: Generate full sky distribution of found frames with 1 degree resolution. The data is presented as 
  interactive RA/DEC chart.
- **Points of interest**: Generate a list of the most commonly photographed coordinates in the sky.
- **Objects and frames search**: Ability to find catalog objects and frames based on specified RA/DEC coordinates and radius.
- **4 Catalogs**: Provides 4 catalogs (NGC, IC, Messier, and Caldwell) in a DB format and a basic interface to query it.
- **PixInsight integration**: This is in the very early stages. The idea is that Hevelius will be able to offload certain
  tasks to Pix or at least export/import data in a format that's compatible with PixInsight.
- **Command line iterface**: Currently Hevelius has a command line interface written in `python`. A Rest API and gui front-end
  is planned, but currently not a priority.
- **Ability to search based on distance**. Implemented proper Haversine formula.

## Documentation

- [Installation](doc/install.md) - You probably want to start here.
- [Commands reference](doc/commands.md) - Available commands are (or soon will) be documented here.
- [Catalogs](doc/catalogs.md) - Hevelius comes with several astronomical catalogs.
- [Database details](doc/db.md) - The most useful section is probably the paragraph about DB initalization.

## Developer's corner

- [Developer's guide](doc/devel.md)
- [Security info](SECURITY.md)
- [License](LICENSE)
