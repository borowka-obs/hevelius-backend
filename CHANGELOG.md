# Hevelius Backend Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project versioning adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.6.0 (unreleased)
- DB: schema bumped to 22: asteroids data now available.
- DB: schema bumped to 23: camera rotation, camera details in the projects.
- DB: schema bumped to 24: asteroid tags (`asteroid_tags`, `asteroid_tag_map`) for
  families / NEO / PHA / etc., with list filtering by tag (`any` / `all`).
- API: asteroid list/detail (`GET`/`POST /api/asteroids`, `GET /api/asteroids/{id}`),
  per-asteroid night visibility curve (`GET /api/asteroids/{id}/visibility`), and
  tag CRUD plus attach/detach endpoints.
- CLI: asteroid download/load from MPCORB and bulk night visibility listing.
- Fix: MPCORB permanent-number unpacking (plain, letter-coded, and tilde/base-62 forms).
- API: The telescopes now have a default camera rotation. The projects now have camera rotation.
  If not specified, the default from the telescope is copied.
- CLI: It's possible to specify default rotation for a telescope, and an image rotation for
  a project.
- CLI: `hevelius asteroid download` skips MPC when the local cache is younger than 7 days
  (prints the reason); use `--force` to re-download. Download failures are logged clearly.
- CLI: `hevelius asteroid status` reports MPCORB cache location/age and DB asteroid counters.
- CLI: `hevelius asteroid load` upserts orbital elements from the cached MPCORB file into the DB.

## 0.5.1 (2026-05-26)

- CLI: `hevelius catalogs` lists installed catalogs with object counts (`--sort entries|name`).
- CLI: `hevelius catalog` searches catalog objects by name, catalog, constellation,
  and optional coordinates (`--ra`/`--dec`, `--radius`, `--sort`, `--limit`).
- API: `GET /api/catalogs` lists installed catalogs with object counts (`sort=entries|name`).
- API: `GET/POST /api/catalogs/list` supports coordinate proximity search (`ra`, `decl`,
  `proximity`) and matches object `name` or `altname` when filtering by `name`.
- API: `PATCH /api/projects/{project_id}/subframes/{subframe_id}` now updates only
  the columns supplied in the body. `count` and `goal_count` are no longer mirrored,
  so the runner can bump captured-frame counts without disturbing the user-defined
  goal_count or active flag.
- API: project subframes now expose `last_updated` (UTC). The server stamps it on
  every successful PATCH so callers can detect stale rows and skip no-op writes.
- DB: Schema bumped to 21: added `project_subframes.last_updated`.
- API: project publications mechanism added.
- API: projects can be deleted.
- CLI: projects can be deleted.

## 0.5.0 (2026-04-27)

- CLI: User management implemented
- API: Argon2id password hashing implemented
- API: /api/task-find-by-filename call to attempt to find a task by its
  filename
- API: /api/tasks-filename-list paginated list of tasks with bare bones
  info (task id, filename)
- API: /api/task-add can now take optional parameters: project-id, filter-id.
  task can be in DONE state, possible to specify a filename.
- API: /api/task-update supports project_id alias, filter_id, imagename
- API: Projects now support optional `regexps`; subframes support optional `count`
  (backward-compatible with `goal_count`, defaults to 0 when omitted).
- DB: Schema bumped to 19: added `regexps` and `count` to projects.
- DB: Schema bumped to 20: added `last_updated`, `start_date`, `end_date`, `total_integration_time`
  to projects.
- DB: New catalogs available:
  - Gum (diffuse southern H-alpha nebulae)
  - RCW (H-alpha emission regions)
- Tasks list now returns usernames and telescope-id details
- Dependencies updated

## 0.4.0 (2026-03-21)

- Projects support added
  - CLI: list projects (`hevelius projects`)
  - CLI: add new project (`hevelius project add`)
  - CLI: edit existing project (`hevelius project edit`)
  - CLI: get project details (`hevelius project show`)
  - CLI: manage subframes within a project (`project subframe add/edit/remove`)
  - API: list projects (`GET /api/projects`)
  - API: get specific project (`GET /api/projects/{project_id}`)
  - API: add new project (`POST /api/projects`)
  - When adding new project, RA/dec coords are optional. If not specified, a catalog
    lookup will try to resolve them.
  - API: edit existing project (`PATCH /api/projects/{project_id}`)
  - API: add new subframes to a project (`POST /api/projects/{project_id}/subframes`)
  - API: edit or delete existing frames in a project (`PATCH/DELETE subframes`)
  - API: (`POST /api/task-update`) now accepts optional project_ids
  - API: (`POST /api/task-add`) now accepts optional projects_ids
  - API: (`DELETE /api/projects/{project_id}/tasks/{task_id}`) can now remove a task from a project.
  - CLI: (`hevelius project task-remove <project_id> <task_id>`) can now remove a task from a project.
- Project statistics added
  - API: (`GET /api/projects/{project_id}/stats`) added, it lists total tasks, number of incomplete and
    complete tasks.
  - CLI: (`hevelius project stats <project_id>`) added, shows statistics for a project.
- Filters support added
  - CLI: list filters (`hevelius filters`)
  - CLI: add, edit filters (`hevelius filter`)
  - API: GET /api/filters
  - CLI: added --active-only for filters (omits inactive filters)
- Sensors support added
  - API: GET /api/sensors
  - CLI: list sensors (`hevelius sensors`)
  - CLI: added --active-only for sensors (omits inactive sensors)
- Telescopes list can now be filtered
- Tasks list can now be filtered by project_ids
- Tasks list and task-get include project_ids.
- DB: Schema bumped to 16: Projects scope and subframe goal
  - projects: added scope_id (NOT NULL, FK to telescopes).
  - project_subframes: renamed count to goal_count.
- DB: Schema bumped to 15: Filters, sensors, and projects
  - filters: New entity with short_name (8 chars or less), full_name, filter_id, url,
    active (default true). Many-to-many with telescopes via telescope_filters.
  - sensors: Extended with vendor, url, active (default true). Telescope uses at most one camera;
    same camera can be used on multiple telescopes.
  - projects: name, description, ra, decl, scope_id; project_subframes
    (filter, exposure_time, goal_count, active);
    project_users (many-to-many); task_projects (task ↔ project many-to-many).
- API: fixed catalog sorting by magnitude, constellation
- API: fixed catalog filtering
- API: added catalog tests
- DB: New catalogs available:
  - Cederblad (Ced) catalog of bright diffuse Galactic nebulae added
  - van den Bergh (vdB) catalog of reflection nebulae added
  - Sharpless-2 (Sh-2) catalog of H II regions added
  - Lynd's Bright Nebulae (LBN) catalog added
  - Lynd's Dark Nebulae (LDN) catalog added
  - Barnard catalog of dark objects added
  - Collinder (Col) catalog of open star clusters, updated added

## 0.3.0 - 2025-04-22

- Pagination added for tasks
- Sorting added for tasks
- Filtering added for tasks
- Telescopes list added
- Catalogs list and object search added

## 0.2.0 - 2025-03-09

- Added support for `hevelius version` command
- Added /api/version endpoint (for getting version information)
- Added /api/task-get endpoint (for getting task details)
- Added /api/task-update endpoint (for updating task state)
- Corrected new tasks to be in state 1 (new), not 0 (template)
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
