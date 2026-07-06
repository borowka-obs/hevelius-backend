# Security audit plan

This document proposes focus areas for a security audit of the Hevelius
backend (REST API + CLI). It is a planning document, not the audit findings
themselves.

Context considered: Hevelius is a small-scale deployment (a single or a
handful of amateur observatories), so raw performance/scale hardening is not
a priority. Correctness of authentication, authorization, and data handling
matters more than throughput.

## What was reviewed to build this plan

`heveliusbackend/app.py` (the Flask REST API, ~35 resources), `hevelius/db*.py`,
`hevelius/config.py`, `hevelius/iteleskop.py`, the CLI (`hevelius/cmd_*.py`,
`bin/hevelius`), migrations under `db/`, and third-party dependencies
(`requirements.txt`).

General observations:

- No `eval`/`exec`/`subprocess`/`pickle`/`os.system` calls anywhere in the
  codebase.
- SQL is parameterized throughout; the few places that interpolate column
  names into `ORDER BY`/`UPDATE` clauses build them from fixed allowlists,
  not raw user input.
- Password storage has clearly been hardened already: argon2id with a
  transparent migration path away from legacy MD5 hashes.

So this is not a codebase full of textbook injection bugs. The audit should
focus on things that don't show up in a simple grep.

## Focus areas

### 1. Broken access control (highest priority)

Almost every endpoint uses `@jwt_required()` only, with no check that the
caller owns the resource or holds elevated privilege. Only three endpoints
gate on the `permissions` bit (`/users`, `/users/audit-log`,
`/users/<id>/password-reset-token`).

- Any authenticated user, regardless of privilege, can create/edit/delete
  telescopes, sensors, filters, and projects — actions that read as
  admin-only but are not gated as such.
- `/task-get` and `/task-update` take a bare `task_id` with no ownership
  check — any user can read or modify another user's observation tasks.
- `/task-add` accepts a client-supplied `user_id` with nothing tying it to
  the JWT identity, so a user can create tasks attributed to someone else.

This needs a deliberate decision: is Hevelius meant to be a
single-tenant, trust-everyone deployment (reasonable for a small hobby
observatory), or should ownership/role checks be enforced? Either answer is
fine, but right now it looks like an oversight rather than a decision.

### 2. Authentication & session handling

- No rate limiting or lockout on `/login` or `/auth/password-reset` (no
  `flask-limiter` or equivalent dependency at all) — brute force and token
  guessing are currently unthrottled.
- JWTs carry a 24h expiry with `permissions` baked in as a claim; changes to
  a user's permissions won't take effect until the token expires, since
  claims aren't re-checked against the DB per request.
- Password reset flow (token issuance and consumption): confirm token
  entropy, TTL, and single-use invalidation are all correctly enforced
  end-to-end rather than assuming from a first read.
- Legacy MD5 password migration path: confirm it cannot be abused to force
  a downgrade once a user's password is already migrated to argon2id.

### 3. CORS configuration

`CORS(app, support_credentials=True)` is configured with no `origins`
restriction. With credentials allowed, this typically results in the origin
being reflected rather than a real allowlist being enforced. Worth tightening
to an explicit list of trusted origins.

### 4. Secrets & configuration management

- `hevelius.yaml` holds the DB password and JWT secret in plaintext; confirm
  it is never committed, file permissions are restrictive, and production
  deployments prefer the environment-variable override path.
- `_normalize_jwt_secret()` hashes short JWT secrets up to 32 bytes rather
  than rejecting them; confirm this doesn't silently mask a weak configured
  secret in production instead of failing loudly.

### 5. CLI tools (`hevelius/cmd_*.py`, `bin/hevelius`)

These run with direct DB/filesystem access and sit on a different trust
boundary than the REST API (local operator use). Worth checking:

- `cmd_repo.py` — repo/backup path handling; any path traversal via
  filenames from imported frames.
- `cmd_catalogs.py` / `cmd_catalog.py` — catalog file import, including
  archive handling and parsing of untrusted files.
- `cmd_db_migrate.py` — privileges used to run migrations.

### 6. Database privilege separation

`db/10-db-hardening.psql` suggests least-privilege was already considered.
Worth verifying the application's runtime DB role actually has the intended
restricted grants (no superuser, no DDL at runtime), rather than assuming the
script was applied correctly and never drifted.

### 7. Dependency posture

Dependencies in `requirements.txt` are pinned (Flask 3.1.3, PyJWT 2.12.1,
psycopg2-binary 2.9.10, etc.). Pinning avoids drift but also means patches
aren't automatic — worth a CVE check against the pinned versions.

## Explicitly lower priority

Given the small-scale deployment, the following are reasonable to defer:

- DoS/performance hardening and request throttling for scale.
- Connection pooling and other scalability work.
- The `/histo` endpoint (plotly rendering) — no user input reaches it
  directly, so risk is low.

## Suggested starting point

Start with **access control (#1)**: enumerate every endpoint missing an
ownership or role check, and propose a fix such as a shared
`require_permission()` / `require_owner_or_admin()` decorator applied
consistently across resources.
