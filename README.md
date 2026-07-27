![pylint](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/pylint.yml/badge.svg)
![pytest](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/testing.yml/badge.svg)
![CodeQL](https://github.com/tomaszmrugalski/hevelius-backend/actions/workflows/github-code-scanning/codeql/badge.svg)

# hevelius-backend

This is the backend interface ("server") for Hevelius, an astronomy processing software and
observatory management system. The other components are [hevelius-web](https://github.com/borowka-obs/hevelius-web) (web
interface) and [hevelius-runner](https://github.com/borowka-obs/hevelius-runner) (the software you run on Windows on your
PC that controls the telescope).

## Current capabilities (command-line)

Status as of July 2026:

- **Cameras**: You can define cameras - list, add, edit, assign filters
  to them, etc.
- **Filters**: You can define filters - list, add, edit assign them to
  cameras, etc.
- **Telescopes**: You can define telescopes, with specific camera and
  filters.
- **Projects**: Specify what objects to image with target list of
  subframes, which telescope to use and more.
- **Objects and frames search**: Ability to find catalog objects and frames based on specified RA/DEC coordinates and radius.
- **Many Catalogs**: NGC, IC, Messier, and Caldwell and also some less popular ones. See below for a full list.
- **Asteroid observation planning**: Download MPC orbital elements for 1M+ asteroids and find which ones are
  visible from your site on a given night, with magnitude and altitude filters.
- **CLI**: Hevelius has a command line interface.
- **API**: Hevelius has a Rest API that's being used by Hevelius web
  interface.
- **Users**: Users can be added (via CLI only for now), they can log in
  using the web interface and use the system. They can also tweak their
  own parameters and reset password, if forgotten.
- **Ability to search based on distance**. Implemented proper Haversine formula.
- **Database management**: Schema versioning and upgrades, backup, etc.
- **Configuration**: Config file support and some limited environment variables.
- **Doctor**: `hevelius doctor` checks that the install is configured correctly (config, DB
  connectivity/schema, logs, JWT/web-url/SMTP settings) and can send a test email.

## Hevelius web interface

Hevelius provides a nice web interface. See
https://github.com/borowka-obs/hevelius-web for details.

## Hevelius runner

Hevelius runner is a small tool that's supposed to run on a machine which
controls the telescope. It provides various capabilities, such as
reporting acquired frames, reporting statistics etc. For details, see
https://github.com/borowka-obs/hevelius-runner

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
