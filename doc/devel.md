# Hevelius Backend Developer's Guide

To run backend locally, run:

```shell
pip install -e .
python -m hevelius.api
# or: flask --app hevelius.api:app run
```

## Useful developer tasks

1. Check code with pylint: `pylint --rcfile .pylint $(git ls-files '*.py') bin/hevelius`

2. Check code with flake8: `flake8 --config .flake8 --color=auto $(git ls-files '*.py') bin/hevelius`

3. Fix trivial esthetics in the code: `autopep8 --in-place --max-line-length 160 --aggressive --aggressive $(git ls-files '*.py')`

4. Run Flask app: `python -m hevelius.api` (add `--host`/`--port` to change the bind address, e.g. `--host 0.0.0.0 --port 5001`)

5. Retrieve the list of tasks (the API is JWT-authenticated; log in first to get a token):

```shell
TOKEN=$(curl -s -X POST http://127.0.0.1:5001/api/login \
    -H 'Content-type: application/json' \
    -d '{"username": "thomson", "password": "secret1"}' | jq -r .token)

curl -s http://127.0.0.1:5001/api/tasks?user_id=3\&per_page=10 \
    -H "Authorization: Bearer $TOKEN"
```

## Running in gunicorn

```shell
gunicorn -w 1 -b 0.0.0.0:5001 'hevelius.api:app'
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

`tests/dbtest.py` keeps one migrated template database per `pytest` run and clones
test databases from it, instead of running the full incremental migration for every
test case:

- First test: creates the test DB, runs the full incremental migration
  (`hevelius db migrate`) against it, then saves it as a `..._template` database.
- Every later test: clones a fresh test DB from that template with
  `CREATE DATABASE ... WITH TEMPLATE ...` (near-instant — a filesystem-level copy),
  skipping the migration entirely.
- Test data (e.g. `tests/test-data.psql`) is loaded into the cloned DB after cloning,
  per test case — it is not baked into the shared template.
- At process exit, the template database is dropped (via `atexit`).

Set `HEVELIUS_DEBUG=1` to keep the per-test database around afterwards instead of
dropping it, for debugging.
