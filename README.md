![pylint](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/pylint.yml/badge.svg)
![pytest](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/testing.yml/badge.svg)
![CodeQL](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/github-code-scanning/codeql/badge.svg)

# hevelius-backend

This is a backend interface for Hevelius, an astronomy processing software and
observatory management system. It's in the early stages of development, but some
of the features are usable already.

## Current capabilities (command-line)

Status as of Feb 2026:

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
- **Command line iterface**: Currently Hevelius has a command line interface written in `python`.
- **Web interface**.
- **Rest API**.
- **Ability to search based on distance**. Implemented proper Haversine formula.
- **Database management**: Schema versioning and upgrades, backup, etc.
- **Configuration**: Config file support and some limited environment variables.

## Current capabilities (REST API)

- Log in users
- List tasks (with pagination, filtering, and sorting)
- Add new observation task
- Edit existing observation task
- Catalogs support: List objects, search objects, filter objects by name, catalog, constellation
- Search objects in catalogs
- Display heat map of the sky (sky map colored with number of photos taken in each square degree)

## Catalogs

The following catalogs are currently available. Each is stored as separate SQL file, so desired catalogs
can be loaded.

| Short | Catalog | Source | Records |
|-------|---------|--------|---------|
| B | Barnard (dark objects) | VII/220A | 349 |
| C   | Caldwell | | 109 |
| Ced | Cederblad (bright diffuse Galactic nebulae) | VII/231 | 330 |
| Col | Collinder (open star clusters, updated) | CloudyNights article | 471 |
| NGC | New General Catalog | | 8418 |
| IC  | Index Catalog       | | 4767 |
| LBN | Lynd's Bright Nebulae | VII/9 | 1125 |
| LDN | Lynd's Dark Nebulae | VII/7A | 1791 |
| M   | Messier Catalogue   | | 110 |
| Mel | Melotte (star clusters) | In-The-Sky.org | 245 |
| Sh2 | Sharpless (H II regions) | VII/20 | 313 |
| vdB | van den Bergh (reflection nebulae) | VII/21 | 158 |


## Documentation

- [Installation](doc/install.md) - You probably want to start here.
- [Commands reference](doc/commands.md) - Available commands are (or soon will) be documented here.
- [Catalogs](doc/catalogs.md) - Hevelius comes with several astronomical catalogs.
- [Database details](doc/db.md) - The most useful section is probably the paragraph about DB initalization.

## Developer's corner

- [Developer's guide](doc/devel.md)
- [Security info](SECURITY.md)
- [License](LICENSE)
