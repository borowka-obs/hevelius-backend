## Commands documentation

There are two interfaces for the Hevelius system: web (in very early stages of
development) and command line. The command-line can be accessed the following
way:

```
$ python bin/hevelius
Hevelius

usage: hevelius [-h]
  {db,config,version,data,repo,catalogs,catalog,filters,filter,sensors,sensor,projects,project,telescopes,telescope,users,user} ...

positional arguments:
  db                    Manages database (version, migrate, backup, stats)
  config                Shows current Hevelius (DB, file repository) configuration
  version               Shows the current Hevelius package version
  data                  Data mining (distrib, groups, catalog)
  catalogs              List installed astronomical catalogs
  catalog               Search astronomical catalog objects
  repo                  Manages files repository on local storage
  filters               List optical filters
  filter                Add or edit a filter
  sensors               List sensors (cameras)
  sensor                Add or edit a sensor
  projects              List projects or show one by ID
  project               Add, edit, show project; subframes; task assignment; stats
  telescopes            List telescopes
  telescope             Add, edit, show telescope; sensor and filter associations
  users                 List all users (summary, no passwords)
  user                  Add, enable, or disable a user (see below)

options:
  -h, --help            show this help message and exit
```

Run `python bin/hevelius COMMAND --help` for subcommands (e.g. `hevelius db migrate --help`).

### User management (CLI)

- **users** – Lists users: id, login, name, email, permissions, whether web login is allowed (`pass_d` set), AAVSO id.
- **user add** – `hevelius user add LOGIN --password PASSWORD [--firstname …] [--lastname …] [--email …] [--phone …] [--share …] [--permissions N] [--aavso-id …]`. Stores **argon2id** in `pass_d`. Login must be unique.
- **user disable** – `hevelius user disable LOGIN_OR_USER_ID` clears `pass` and `pass_d` so the account cannot log in.
- **user enable** – `hevelius user enable LOGIN_OR_USER_ID --password NEW_PASSWORD` sets `pass_d` (argon2id).

User add / enable / disable actions are recorded in the **user_admin_audit** table (schema 18+).

### Database

- **db version** – Current schema version from `schema_version`.
- **db migrate** – Apply pending `db/*.psql` migrations (PostgreSQL).
- **db backup** – Database backup.
- **db stats** – Database statistics.

### Catalogs – list and search astronomical objects

- **catalogs** – List catalogs loaded in the database with object counts.
  `hevelius catalogs [--sort entries|name]` (default sort: by object count).
- **catalog** – Search catalog objects: `hevelius catalog [NAME] [--catalog SHORTNAME]
  [--const CODE] [--ra HH MM SS] [--dec +DD MM SS] [--sort FIELD] [--sort-order asc|desc]
  [--limit N]`. See `doc/catalogs.md` for details.

### Data catalog – objects near coordinates and matching frames

The **data catalog** subcommand finds catalog objects and observation frames near
a sky position. There are two ways to specify the position. First, use a catalog
name: `--object M1`. If the object is found, its coordinates are used. Alternatively,
specify coordinates directly: `--ra "11 22 33" --decl "-22 33 44"`. In both cases,
set the search radius with `--proximity 2.0` (default 1 degree).

Hevelius lists nearby catalog objects and frames in the database. Use
`--format XXX` for output: `none`, `filenames`, `csv`, `brief`, `full`, `pixinsight`.

The `pixinsight` format is for PixInsight SubframeSelector (Process → ImageInspection
→ SubframeSelector → edit instance source code → paste into `P.subframes`).

Example:

```bash
python bin/hevelius data catalog --object C38 --proximity 0.5 --format full
```

### Filters, sensors, and projects (schema 15+)

- **filters** – List optical filters (short name, full name, URL, active). Use `--active-only` to show only active filters.
- **sensors** – List sensors/cameras (resolution, pixel size, bit depth, vendor, URL, active). Use `--active-only` to show only active sensors.
- **projects** – List projects (ID, name, scope_id, RA, Dec, active, description). Optionally pass a project ID to show one project with its subframes (filter, exposure time, goal_count, active) and associated user IDs.
- **project add** – Create a project: `hevelius project add NAME --scope-id ID [--ra HOURS] [--dec DEGREES] [--description TEXT]`. Name and scope_id are required. If `--ra` and `--dec` are omitted, coordinates are resolved from the catalog by name; if not found, the command fails.
- **project edit** – Update a project: `hevelius project edit PROJECT_ID [--name NAME] [--scope-id ID] [--description TEXT] [--ra HOURS] [--dec DEGREES] [--active|--inactive]`.
- **project show** – Show one project: `hevelius project show PROJECT_ID`.
- **project subframe add** – Add a subframe: `hevelius project subframe add PROJECT_ID --filter-id ID --exposure-time SEC [--goal-count N] [--active|--inactive]`.
- **project subframe edit** – Edit a subframe: `hevelius project subframe edit PROJECT_ID SUBFRAME_ID [--filter-id ID] [--exposure-time SEC] [--goal-count N] [--active|--inactive]`.
- **project subframe remove** – Remove a subframe: `hevelius project subframe remove PROJECT_ID SUBFRAME_ID`.

Example:

```bash
python bin/hevelius filters
python bin/hevelius sensors --active-only
python bin/hevelius projects
python bin/hevelius projects 1
```

### REST API (user-related)

Authenticated clients can use **GET /api/users/me** for the current user profile (no passwords). Administrators (permissions bit 0) can **GET /api/users**, **GET /api/users/audit-log**, and **POST /api/users/{user_id}/password-reset-token**. Anyone with a valid reset token can call **POST /api/auth/password-reset** (no JWT). See `api/openapi.yaml` for full contracts.
