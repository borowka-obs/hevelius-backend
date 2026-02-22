# Installation

## For Users

Simple installation for users is not yet available. Please set up the
development environment as explained in the "For Developers" section.

## For Developers

1. Setup virtual environment: `python -m venv venv`
2. Enable virtual environment: `source venv/bin/activate`
3. Update pip: `pip install --upgrade pip`
4. Install dependencies: `pip install -r requirements.txt`

## Set up PostgreSQL database

You need to have a PostgreSQL installation available. Please consult
PostgreSQL documentation for details.

```shell
apt install postgresql postgresql-client
su - postgres
psql
CREATE DATABASE hevelius;
CREATE USER hevelius WITH PASSWORD 'secret'; -- use an actual password here
GRANT ALL PRIVILEGES ON DATABASE hevelius TO hevelius;
```

Starting with schema 14, an extension is necessary. You need to connect to
a hevelius database, either using `psql hevelius` or using `\c hevelius`, then:

```
CREATE EXTENSION pg_trgm;
```

If you're on Postgres 15 or later, you likely want to also do this:

```
ALTER DATABASE hevelius OWNER to hevelius;
```
Otherwise you might get ` permission denied for schema public` when trying to initialize the db.

## Configure Hevelius-backend

The configuration is currently very basic. Please copy
`hevelius/hevelius.yaml.example` to `hevelius/hevelius.yaml` and edit its content.
You will need to set up things like DB credentials, repository path (where your
image frames are kept on disk) and others.

## Initialize the database

To initialize the schema, use the following command:

```
 bin/hevelius db migrate
 bin/hevelius db version
```

## Running Hevelius (command-line)

```shell
source venv/bin/activate
$ python bin/hevelius
```

## Running Hevelius (REST API)

```shell
source venv/bin/activate
python -m flask --app heveliusbackend/app.py run
```
