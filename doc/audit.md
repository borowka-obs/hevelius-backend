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

### 1. Broken access control (highest priority) — verified findings

**Status: reviewed in detail.** The initial pass over this area (below) turned
out to be partly wrong; `/task-add` and `/task-update` do check ownership.
The corrected, verified list follows.

Only three endpoints gate on the `permissions` bit (`_jwt_permissions_int() & 1`):
`/users` (app.py:1354), `/users/audit-log` (app.py:1254), and
`/users/<id>/password-reset-token` (app.py:1309). Everything else that
requires authentication uses `@jwt_required()` only.

**Confirmed real gaps:**

- `/task-get` (app.py:1731-1830) — no ownership check at all; any
  authenticated user can fetch any task by ID, including its `imagename`
  (file path).
- `GET`/`POST /tasks` (app.py:1473-1670) — the `user_id` filter parameter is
  unrestricted (app.py:~1514); any user can list any other user's tasks in
  full detail.
- `/task-find-by-filename` (app.py:1673-1689) and `/tasks-filename-list`
  (app.py:1692-1718) — no owner filtering; return `task_id`/`imagename` for
  every task in the database to any authenticated user. Minor but real
  information disclosure (file-path layout, other users' work).
- `/scopes` POST, `/scopes/<id>` PATCH, `/scopes/<id>/filters` POST/DELETE
  (app.py:2045-2168), `/filters` POST/PATCH (app.py:2229-2312), `/sensors`
  POST/PATCH (app.py:2358-2455) — gated by `@jwt_required()` only; any
  authenticated user, regardless of role, can create/edit the hardware
  inventory (telescopes, sensors, filters).
- `/projects` POST (app.py:2620), `/projects/<id>` PATCH/DELETE
  (app.py:2719-2773), `/projects/<id>/subframes` POST/PATCH/DELETE
  (app.py:2793-2880) — **no ownership or membership check at all**; any
  authenticated user can edit or delete *any* project, including ones they
  are not assigned to.
- **Data model finding:** a `project_users` table exists and is populated
  (joined at app.py:2568, 2603, 2670, 2704, 2749), exposed via
  `ProjectSchema.user_ids`. It is used only as an optional query filter
  (`GET /projects?user_id=`), never as an authorization boundary. The schema
  clearly models "users assigned to a project" but the API never enforces it
  — the cleanest evidence that an ownership model exists in the data but was
  never wired into access control.

**Confirmed NOT a gap (corrects the original draft of this section):**

- `/task-add` (app.py:1387) checks `task_data['user_id'] != current_user_id`
  and rejects the request unless `app.testing` is set. Not exploitable in
  production — `app.testing` is only ever set in `tests/*.py`. Minor
  defense-in-depth note: it's a mutable attribute on the singleton `app`
  object rather than request-scoped, so if a future code path sets it without
  resetting, the check would silently disable process-wide; worth a comment
  or a more explicit guard if this is a concern.
- `/task-update` (app.py:1836-1839) checks task ownership before allowing an
  update; a user cannot modify another user's task through this endpoint.
- `/projects/<id>/tasks/<id>` POST/DELETE (app.py:2916-2949) checks task
  ownership before linking/unlinking it from a project.

**Fix recommendations (not yet implemented):**

1. Add a `require_admin()` decorator (checks `_jwt_permissions_int() & 1`)
   and apply it to: `ScopesResource.post`, `ScopeDetailResource.patch`,
   `ScopeFiltersResource.post`, `ScopeFilterRemoveResource.delete`,
   `FiltersResource.post`, `FilterDetailResource.patch`,
   `SensorsResource.post`, `SensorDetailResource.patch`.
2. Add a `require_project_member_or_admin(project_id)` check (query
   `project_users` for the JWT user, or admin bit) and apply it to
   `ProjectDetailResource.patch/delete`, `ProjectSubframesResource.post`,
   `ProjectSubframeDetailResource.patch/delete`. `ProjectsResource.post`
   (project creation) could auto-insert the creator into `project_users`.
3. For `/task-get`, `/task-find-by-filename`, `/tasks-filename-list`: either
   add an ownership filter (join to JWT user unless admin), or explicitly
   document that read access to task metadata is intentionally shared across
   all authenticated users (a legitimate choice for a small, trusted
   deployment) — it should be a stated decision, not a silent default.
4. For the `TasksResource` `user_id` filter: no change needed if the
   read-sharing model in point 3 is the accepted one; otherwise restrict
   non-admins to their own `user_id`.

This needs a deliberate decision either way: is Hevelius meant to be a
single-tenant, trust-everyone deployment (reasonable for a small hobby
observatory), or should ownership/role checks be enforced on the write paths
listed above? Right now it looks like an oversight rather than a decision.

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
