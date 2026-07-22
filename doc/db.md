# Setting up Postgres database

Setting up a new database goes the usual way. Do `sudo -u postgres psql postgres`, then:

```sql
CREATE USER hevelius WITH PASSWORD 'secret1';
CREATE DATABASE hevelius;
GRANT ALL PRIVILEGES ON DATABASE hevelius TO hevelius;
```

# Database migration (from iteleskop)

Then run the following command to import iteleskop schema with Hevelius changes:

```python
python bin/hevelius migrate
```

## Schema info

he_solved_ra - Right Ascension, from the plate solving, in degrees (0-359)

### Schema version 24 (asteroid tags)

- **asteroid_tags** – Shared tag vocabulary for asteroids (`name` unique, optional
  `description` / `color`). Examples: neo, pha, amor, fast rotator.
- **asteroid_tag_map** – Many-to-many link (`asteroid_id`, `tag_id`) with cascade
  deletes; index on `tag_id` for reverse lookups and multi-tag list filters.

### Schema version 23 (project rotation, optical params, telescope default rotation)

- **projects** – Added **rotation** (float, degrees East of North, nullable; user-supplied or defaulted
  from the telescope, see below) and **focal**, **resx**, **resy**, **pixel_x**, **pixel_y** (optical
  parameters, copied from the telescope's attached sensor at creation time, all nullable).
- **telescopes** – Added **default_rotation** (float, degrees East of North, nullable). When a new
  project is created on a telescope without an explicit `rotation`, it is copied from the telescope's
  `default_rotation` (if set); otherwise the project's `rotation` stays NULL.

### Schema version 22 (asteroids)

- **asteroids** – MPC orbital elements for visibility planning (`designation`, epoch, Keplerian
  elements, absolute magnitude / slope). Used by asteroid night-visibility queries and the
  REST asteroid list/detail/visibility API.

### Schema version 18 (users cleanup, audit, password reset)

- **users** – **ftp_login** and **ftp_pass** removed. Non-empty **login** values are unique (partial unique index where `login IS NOT NULL`). Empty-string logins are normalized to NULL before the constraint is applied.
- **user_admin_audit** – Append-only log: `channel` (`api` / `cli`), `actor_user_id`, `action`, `target_user_id`, `details` (JSONB), `created_at`.
- **password_reset_tokens** – One-time hashed tokens for password reset; `expires_at`, `consumed_at`.

### Schema version 16 (projects scope, subframe goal_count)

- **projects** – Added **scope_id** (integer NOT NULL, FK to telescopes). Each project is tied to one telescope.
- **project_subframes** – Column **count** renamed to **goal_count** (target number of subframes).

### Schema version 15 (filters, sensors, projects)

- **filters** – Optical filters: filter_id (PK), short_name (≤8 chars), full_name, url, active (default true). Many-to-many with telescopes via **telescope_filters**.
- **sensors** – Extended with vendor, url, active (default true). Telescope uses at most one sensor (camera); the same sensor can be used on multiple telescopes.
- **projects** – name, description, scope_id, ra, decl, active (default true). **project_subframes**: filter_id, exposure_time, goal_count (integer), active (default true). **project_users**: many-to-many with users. **task_projects**: tasks can belong to zero or more projects.


## Setting up MySQL database (obsolete)

Setting up a new database goes the usual way:

```sql
CREATE DATABASE hevelius;
CREATE USER 'hevelius'@'192.0.2.1' IDENTIFIED BY 'password';
GRANT ALL on hevelius.* to 'hevelius'@'192.0.2.1';
```
