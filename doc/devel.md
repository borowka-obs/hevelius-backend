# Hevelius Backend Developer's Guide

To run backend locally, run:

```shell
export PYTHONPATH=.:..
cd havelius/
python3 -m flask --app 'heveliusbackend.app:app' run
```

## Useful developer tasks

1. Check code with pylint: `pylint --rcfile .pylint $(git ls-files '*.py') bin/hevelius`

2. Check code with flake8: `flake8 --config .flake8 --color=auto $(git ls-files '*.py') bin/hevelius`

3. Fix trivial esthetics in the code: `autopep8 --in-place --max-line-length 160 --aggressive --aggressive $(git ls-files '*.py')`

4. Run Flask app: `python -m flask --app heveliusbackend/app.py run`

5. Retrieve the list of tasks:

curl -X POST http://127.0.0.1:5000/api/tasks -H 'Content-type: application/json' -d '{  limit: 10, user_id: 3, password: "digest-here" }'

## Running in gunicorn

```shell
gunicorn -w 1 -b 0.0.0.0:5000 'heveliusbackend.app:app'
```

## Running tests

`python -m pytest -s -v`

If you get an error about insufficient permissions to create a database, you
can do the following:

```SQL
ALTER USER hevelius CREATEDB;
```

If you want keep the database after test, set HEVELIUS_DEBUG env variable, e.g.:

`HEVELIUS_DEBUG=1 python -m pytest -s -v`

You need to provide database password when running tests. One way is to set the
PGPASSWORD variable. Another is to set an entry in `~/.pgpass` file. The format
is `hostname:port:database_name:username:password` e.g.

```
localhost:5432:hevelius:hevelius:secret1
```


## Fast DB tests

The DB can be run in two modes: slow (using incremental migrations) or fast (using template database).

Here's the final comparison:

Performance Results

------------------------------|---------------|--------
Mode                          | 57 tests      | Speedup
------------------------------|---------------|----
Fast (template database)      |	~10.2 seconds | ~4x faster
------------------------------|---------------|--------
Slow (incremental migrations) |	~39.9 seconds | baseline

The DB template solution that makes your tests run approximately 4x faster while keeping the incremental schema files for production deployments. Here's what was created/modified:

The consolidated schem is available in db/schema-consolidated.psql - A consolidated schema file representing the final schema state (version 14). This is used only for testing and contains all tables, indexes, and constraints in their final form.

tests/conftest.py - A pytest configuration file that automatically cleans up template databases at the end of the test session.

tests/dbtest.py - Updated to use PostgreSQL's template database feature:
Creates template databases once per test session (one per unique load_test_data file)
Uses CREATE DATABASE ... TEMPLATE to clone databases instantly
Falls back to incremental migrations if HEVELIUS_SLOW_TESTS=1 is set

Automatically handles different test data files with separate templates

How It Works

First test run: Creates a template database using the consolidated schema + test data
Subsequent tests: Clone the template database (nearly instant via filesystem copy)
End of session: Clean up all template databases

Environment Variables

Default behavior: Fast mode using template databases
HEVELIUS_SLOW_TESTS=1: Use incremental migrations (useful for testing the actual migration path)
HEVELIUS_DEBUG: Keep test databases for debugging

Keeping Schema in Sync

When you add new incremental migration files, you'll need to update db/schema-consolidated.psql to reflect the changes. The consolidated file includes a comment header explaining this. You can either:
Manually update it based on the new migration
Apply all migrations to a fresh database and dump the schema