![pylint](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/pylint.yml/badge.svg)
![pytest](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/testing.yml/badge.svg)
![CodeQL](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/github-code-scanning/codeql/badge.svg)

# hevelius-backend

This is the backend interface ("server") for Hevelius, an astronomy processing software and
observatory management system. The other components are [hevelius-web](https://github.com/borowka-obs/hevelius-web) (web
interface) and [hevelius-runner](https://github.com/borowka-obs/hevelius-runner) (the software you run on Windows on your
PC that controls the telescope).

## Current capabilities (command-line)

Status as of May 2026:

- **Scan FITS repository on disk**: Hevelius is able to scan a local disk for FITS files, extract some data from found files
  (from filenames and FITS header) and put this information into PostgreSQL DB. Then the DB is used to report various
  characteristics.
- **Full sky histogram**: `GET /api/tasks/histogram` returns a sparse 1° sky
  density map of completed plate-solved frames.
- **Points of interest**: Generate a list of the most commonly photographed coordinates in the sky.
- **Objects and frames search**: Ability to find catalog objects and frames based on specified RA/DEC coordinates and radius.
- **Many Catalogs**: NGC, IC, Messier, and Caldwell and also some less popular ones. See below for a full list.
- **PixInsight integration**: This is in the very early stages. The idea is that Hevelius will be able to offload certain
  tasks to Pix or at least export/import data in a format that's compatible with PixInsight.
- **Command line iterface**: Currently Hevelius has a command line interface written in `python`.
- **Web interface**.
- **Rest API**.
- **Ability to search based on distance**. Implemented proper Haversine formula.
- **Database management**: Schema versioning and upgrades, backup, etc.
- **Configuration**: Config file support and some limited environment variables.
- **Asteroid observation planning**: Download MPC orbital elements for 1M+ asteroids and find which ones are
  visible from your site on a given night, with magnitude and altitude filters.

## Current capabilities (REST API)

- Log in users, with strong, modern crypto (Argon2id)
- Observation tasks management (with pagination, filtering, and sorting)
- Observation projects management (a campaign of many subframes of the same object)
- Telescopes management (add, edit telescopes)
- Filters management (add, edit, activate/deactivate filters)
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
| Gum | Gum (diffuse southern H-alpha nebulae) | GalaxyMap gum.xls compilation | 97 |
| IC  | Index Catalog       | | 4767 |
| NGC | New General Catalog | | 8418 |
| LBN | Lynd's Bright Nebulae | VII/9 | 1125 |
| LDN | Lynd's Dark Nebulae | VII/7A | 1791 |
| M   | Messier Catalogue   | | 110 |
| Mel | Melotte (star clusters) | In-The-Sky.org | 245 |
| RCW | RCW (H-alpha emission regions) | VII/216 | 181 |
| Sh2 | Sharpless (H II regions) | VII/20 | 313 |
| vdB | van den Bergh (reflection nebulae) | VII/21 | 158 |


## Documentation

- [Installation](doc/install.md) - You probably want to start here.
- [Commands reference](doc/commands.md) - Available commands are (or soon will) be documented here.
- [Catalogs](doc/catalogs.md) - Hevelius comes with several astronomical catalogs.
- [Asteroid observation planning](doc/asteroids.md) - Algorithm and CLI reference for asteroid visibility.
- [Database details](doc/db.md) - The most useful section is probably the paragraph about DB initalization.

## Developer's corner

- [Developer's guide](doc/devel.md)
- [Security info](SECURITY.md)
- [License](LICENSE)
