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

### Schema version 15 (filters, sensors, projects)

- **filters** – Optical filters: filter_id (PK), short_name (≤8 chars), full_name, url, active (default true). Many-to-many with telescopes via **telescope_filters**.
- **sensors** – Extended with vendor, url, active (default true). Telescope uses at most one sensor (camera); the same sensor can be used on multiple telescopes.
- **projects** – name, description, ra, decl, active (default true). **project_subframes**: filter_id, exposure_time, count (integer), active (default true). **project_users**: many-to-many with users. **task_projects**: tasks can belong to zero or more projects.


## Setting up MySQL database (obsolete)

Setting up a new database goes the usual way:

```sql
CREATE DATABASE hevelius;
CREATE USER 'hevelius'@'192.0.2.1' IDENTIFIED BY 'password';
GRANT ALL on hevelius.* to 'hevelius'@'192.0.2.1';
```
