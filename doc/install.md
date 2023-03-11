# Installation (for users)

Simple installation for users is not yet available. Please set up the
development environment as explained in Installation for developers.


# Installation (for developers)

1. Setup virtual environment: `python -m venv venv`
2. Enable virtual environment: `source venv/bin/activate`
3. Update pip: `pip install --upgrade pip`
4. install dependencies: `pip install -r requirements.txt`

# Set up PostgreSQL database

You need to have a PostgreSQL installation available. Please consult
PostgreSQL documentation for details.


```
apt install postgresql postgresql-client
su - postgres
psql
CREATE DATABASE hevelius;
CREATE USER hevelius WITH PASSWORD 'secret'; -- use an actual password here
GRANT ALL PRIVILEGES ON DATABASE hevelius TO hevelius;
```

# Configure Hevelius-backend

The configuration is currently very basic. Please copy
`hevelius/config.py-example` to `hevelius/config.py` and edit its content.
You will need to set up things like DB credentials, repository path (where your
image frames are kept on disk) and others.
