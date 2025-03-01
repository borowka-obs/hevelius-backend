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

If you want keep the database after test, set HEVELIUS_DEBUG env variable, e.g.:

`HEVELIUS_DEBUG=1 python -m pytest -s -v`

You need to provide database password when running tests. One way is to set the
PGPASSWORD variable. Another is to set an entry in `~/.pgpass` file. The format
is `hostname:port:database_name:username:password` e.g.

```
localhost:5432:hevelius:hevelius:secret1
```
