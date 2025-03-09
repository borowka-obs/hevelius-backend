# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.2.0 - 2025-03-09

- Added support for `hevelius version` command
- Added /api/version endpoint (for getting version information)
- Added /api/task-get endpoint (for getting task details)
- Added /api/task-update endpoint (for updating task state)
- Corrected new tasks to be in state 1 (new), not e (template)
- Added /api/night-plan endpoint (generates observation plan for the night)

## 0.1.0 - 2025-03-02

- ChangeLog added
- Implemented REST API
- Implemented Haversine formula for calculating proper spherical distance calculation (#10)
- Added missing dependency: astropy (#34)
- Schema version updated to 12 (removed vphot, defocus columns in tasks table)
- JWT authentication implemented
- Implemented /api/task-add call that adds new observation task
- First config file support (hevelius.yaml)
- Config handling fixed
- Postgres password is now passed properly during schema updates
- Schema version updated to 12
- Support for gunicorn added
- Many bug fixes

## 0.0.3 - release date unspecified

- Imported data from now defunct iteleskop.org project
- Added catalogs (NGC, IC, Caldwell, Messier)
- Added configuration (hevelius config)
- Added ability to scan FITS files in a repository
- Added data analysis (all sky chart, groups)
