# Setting up MySQL database (obsolete)

Setting up a new database goes the usual way:

```sql
CREATE DATABASE hevelius;
CREATE USER 'hevelius'@'192.0.2.1' IDENTIFIED BY 'password';
GRANT ALL on hevelius.* to 'hevelius'@'192.0.2.1';
```

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
python cmd/db-admin.py migrate
```

## Schema info

he_solved_ra - Right Ascension, from the plate solving, in degrees (0-359)

## TODO

- insert entries for tasks that only have files, but no records in tasks table.
- remove tasks that are not completed
- remove mymfavorites table
