# Observation Scheduler — Design Plan

Status: **draft for review**. This document is meant to be iterated on before any
code is written. It covers four components requested for the telescope
observation scheduler:

> **Revisions (2026-08-03)**: §6 revised after feedback that external
> telemetry (weather, roof state, sensor temperatures, ASCOM state) belongs
> in this picture too — that data class has a genuinely different shape
> than `observation_events` and changes the database recommendation, see
> §6.3. §7 turned into a numbered `OS-#` task breakdown, with telemetry
> (OS-10) deferred as a separate topic.

1. Observation Planning (backlog UI: tasks + projects)
2. Night Plan (per-telescope, per-night subset; read API used by web + runner)
3. Runner support (contract only — implementation is a separate session)
4. Statistics (nightly observing-time reporting, Grafana-ready)

It also answers the four general questions raised alongside the request
(plan sanity check, night-date convention, naming, skeptical review) inline,
plus a dedicated recap at the end.

Repos involved: `hevelius-backend` (this repo, most of the work),
`hevelius-web` (UI), `hevelius-runner` (contract only, no code changes here).

---

## 0. Current state (grounding)

So reviewers don't have to re-derive this: what exists today, as of this
plan, with file references.

- **Tasks** (`tasks` table, `db/07-init.psql`): one-shot "take one image"
  requests. Relevant columns: `scope_id`, `ra`/`decl` (RA in **hours**,
  0–24; see `TaskAddRequestSchema` in `hevelius/api/schemas/__init__.py`),
  `exposure`, `filter` (free varchar, not FK'd to `filters`), `min_alt`,
  `moon_distance`, `max_moon_phase`, `max_sun_alt`, `skip_before`/`skip_after`,
  `min_interval`, `state`. States in use today: `1` NEW, `3` IN QUEUE, `6`
  DONE (per `db/03-state-table.mysql`); `2`/`4` are legacy and unused; `-1`
  DELETED / `-2` DELETED TEMPLATE / `0` TEMPLATE exist but nothing in the API
  currently sets or filters them (no `task-delete` endpoint exists — deletion
  today would have to mean setting `state=-1` via `task-update`, untested).
  `skip_before`/`skip_after`/`created`/`activated`/`performed` are naive SQL
  `timestamp` (no time zone), not `timestamptz`.

- **Projects** (`projects`, `project_subframes`, `task_projects`,
  `project_users`; `db/15…21`, `23`): a project is a fixed RA/Dec target plus
  a set of "subframes" — `(filter_id, exposure_time, goal_count, count)`
  rows. A project is "done" when every active subframe has `count >=
  goal_count`. Crucially, **projects have no observing constraints today** —
  no `min_alt`, `moon_distance`, `max_moon_phase`, `max_sun_alt`, no
  `min_interval`. Only `start_date`/`end_date` exist as coarse date bounds.
  `count` is set by the runner via absolute-value `PATCH
  /api/projects/{id}/subframes/{id}` (`hevelius/api/routes/projects.py`) —
  the caller supplies the new total, there is no per-exposure event log
  behind it.

- **Night plan** (`GET`/`POST /api/night-plan`,
  `hevelius/api/routes/tasks.py:575-673`): this is the "existing, never
  fully implemented" endpoint referenced in the request. It **only** filters
  `tasks` (projects are entirely absent), and the filter is: `scope_id`
  matches, `state IN (1,2,3)`, and `skip_before`/`skip_after` bracket the
  given date. **It does not look at `ra`/`decl` at all** — no altitude, sun,
  or moon check, so it is not actually a visibility filter, just a
  date/state filter. The web client
  (`hevelius-web/src/app/components/night-plan/`,
  `services/night-plan.service.ts`) hard-codes `defaultScopeId = 3`, has no
  date picker, and posts to `/night-plan` with just `scope_id`. The runner
  (`hevelius-runner/src/api_client.py:get_night_plan`) calls the GET variant
  and hands the result to `TaskManager.prepare_sequence_file`
  (`hevelius-runner/src/task_manager.py`), which builds a NINA-style
  sequence from a `{name, ra, dec, filters: [...], exposures: [...]}` shape
  that **does not match the actual `Task` schema** (a task has one filter
  and one exposure, not lists). Per `hevelius-runner/AGENTS.md`: *"The `run`
  automation loop is outdated and may not work — do not treat it as the main
  product path."* This confirms the whole night-plan → sequence pipeline is
  a stub, on both ends, exactly as described in the request.

- **Asteroid visibility** (`hevelius/asteroid.py`,
  `doc/asteroids.md`) is the one place real observability math already
  exists and is battle-tested against ~1M rows: a staged filter (cheap →
  expensive) — SQL magnitude pre-filter, transit-altitude check (one
  subtraction), night hour-angle overlap (trig, no frame transform), apparent
  magnitude, then a precise `astropy` `GCRS → AltAz` transform only for
  survivors. This is the pattern §4.2 below reuses (by extraction into a
  shared module, not by copy-paste).

- **Statistics** (`hevelius/stats.py`): only a sky-density histogram
  (1°×1° bins of completed, plate-solved tasks) and simple `COUNT(*) …
  GROUP BY state/user`. **There is no time-series or per-night data of any
  kind today**, and — importantly — no event log to build one from (see
  §5.2).

- **User preferences** (`db/25-user-preferences-rework.psql`,
  `hevelius/api/routes/auth_users.py`): `GET`/`PATCH /api/users/me/preferences`
  already exists and includes `default_scope` (nullable FK to
  `telescopes`). This is what the Night Plan and Observation Planning UIs
  should read for "pick the default scope."

- **Telescopes** (`telescopes` table): has `lat`/`lon`/`alt` (already used
  by asteroid visibility) and `min_dec`/`max_dec` (mount declination
  limits, currently unused by *any* visibility computation — asteroid
  visibility ignores them too). No time zone field exists.

---

## 1. Terminology and conventions (decided here, used throughout)

### 1.1 Night identity — the NINA "date − 12h" rule

A night is identified by a single calendar date, computed the same way NINA
does it:

```
night_date(scope, t) = date( to_local(t, scope.timezone) − 12h )
```

i.e. convert the instant to the telescope's local civil time, subtract 12
hours, take the date. Worked example (site in `Europe/Warsaw`, no DST
subtlety for simplicity):

| Local time | − 12h | Resulting date | Night label |
|---|---|---|---|
| 2026-08-03 22:00 | 2026-08-03 10:00 | 2026-08-03 | "night of Aug 3" |
| 2026-08-04 03:00 | 2026-08-03 15:00 | 2026-08-03 | "night of Aug 3" |
| 2026-08-04 13:00 | 2026-08-04 01:00 | 2026-08-04 | "night of Aug 4" |

Both the evening and the small-hours-of-the-morning parts of the same
observing session collapse onto one date, which is exactly the property we
want for grouping tasks/statistics/UI by "night."

**This requires a per-telescope time zone**, which does not exist in the
schema today (see §2). NINA can get away without one because it runs on a
single PC with one system time zone; Hevelius is explicitly multi-site
("up to 10 telescopes, multiple locations"), so the same trick needs an
explicit IANA zone (e.g. `Europe/Warsaw`, `Africa/Windhoek`) per telescope
rather than the server's own local time. IANA zones are used (not a fixed
UTC offset) so DST transitions are handled correctly without extra logic.
All *astronomical* math (sunset/sunrise/altitude) stays UTC-internal via
`astropy`, exactly as `hevelius/asteroid.py` does today — the time zone is
used **only** for labeling/bucketing a night by date, never for the physics.

The *window* a `night_date` covers, for querying purposes, is
`[local(night_date 12:00), local(night_date+1 12:00))` converted to UTC.
The actual sunset/sunrise (used for the real visibility computation) is a
strict subset of that window and is computed with the existing
`_get_night_times`-style search seeded near local midnight.

### 1.2 Units — a real gotcha to design around

`tasks.ra` and `projects.ra` (via the `objects` catalog it's resolved from,
see `hevelius/catalogs.py`'s `ra_hours` parameter) are stored in **hours**
(`0–24`), matching `TaskAddRequestSchema`'s
`validate.Range(min=0.0, max=24.0)`. Meanwhile `hevelius/asteroid.py` and
`he_solved_ra` (plate-solve results) work in **degrees** (`0–360`). Any
shared visibility code must convert at the boundary (`ra_deg = ra_hours *
15`) and this needs a unit test guarding it — mixing them up silently
mis-places every target by a factor of 15, not an out-of-range error you'd
notice immediately.

### 1.3 Naming

Settled, not up for further debate: **"Observation Planning" and "Night
Plan"** stay as-is (already load-bearing in route names and client code
across all three repos), and **"runner"** is the one formal name for the
observatory-side software — matches the repo, CLI, and its own docs
already. "Agent" stays fine as an informal word in prose (§5's title keeps
it only because that's how the original request phrased the section), but
it's not a second proper noun in code, config, or API docs.

---

## 2. Data model changes

| Table | Change | Why |
|---|---|---|
| `telescopes` | `+ timezone varchar(64) NOT NULL DEFAULT 'UTC'` (IANA name) | Night-date labeling (§1.1); required once sites span time zones. Existing rows need a real value backfilled by hand at migration time (5–10 telescopes, not automatable from `lat`/`lon` reliably enough to trust). |
| `projects` | `+ min_alt float`, `+ moon_distance float`, `+ max_moon_phase int`, `+ max_sun_alt int`, `+ min_interval int` (all nullable) | Mirrors the same columns on `tasks` so both can go through one visibility engine (§5.2). Today projects have **no** observing constraints at all. |
| `projects`, `tasks` | `+ priority int NOT NULL DEFAULT 0` | *Recommended, not required.* Night Plan and Observation Planning both need *some* ordering signal beyond "visible y/n"; see §8 "no ordering/priority field" for why this is flagged separately rather than assumed. |
| `tasks` | `skip_before`, `skip_after`, `created`, `activated`, `performed` : `timestamp` → `timestamptz` | These are naive today (§0). Fine as long as everything writing them is disciplined about UTC, but that's an invariant enforced by convention only, not the type system — a real footgun across multi-timezone sites. Values are assumed already UTC; migration is a type change, not a value change. |
| new: `observation_events` | see §5.2 | Execution/report event log — becomes the source of truth for project subframe counts *and* all statistics. This table does not exist in any form today; it's the biggest net-new piece of this plan. |
| new: `telemetry_weather`, `telemetry_sensor_temps`, `telemetry_ascom_state`, `telemetry_roof_events` | see §6.4 | External telemetry not tracked anywhere today. First three become TimescaleDB hypertables; roof events stay a plain event-log table (low frequency, same shape as `observation_events`). |

Illustrative migration numbers (next free is 26): `26` telescopes timezone +
project constraint/priority columns, `27` tasks timestamptz conversion, `28`
`observation_events` + derived subframe counts, `29` enable TimescaleDB
extension + telemetry tables/hypertables. Final numbering decided at
implementation time.

---

## 3. Component 1 — Observation Planning

**Goal** (from the request): a UI showing the full backlog — every
task and project — with the ability to edit it. "100s, maybe 1000s of
tasks, 10 or more projects."

### 3.1 Unified list — recommended approach

The request asks for a UI showing "a unified list of tasks and projects."
Given the stated scale (tasks: hundreds–thousands; projects: ~10), I'd
**merge on the frontend, not the backend**:

- Projects: fetch the whole list in one call (existing `GET /api/projects`,
  default page size already 100, ≫ 10-ish projects per scope) — no
  pagination concern.
- Tasks: keep using the existing paginated/filtered/sorted `GET /api/tasks`
  unchanged.
- The Angular component interleaves them for display (e.g., projects
  pinned as their own rows/section, or a real merge-sort client-side since
  project count is trivially small).

The alternative — a single backend endpoint that `UNION`s two
structurally-different row shapes (a task row vs. a project-with-subframes
row) into one polymorphic schema — is more backend machinery for a merge
that's cheap to do client-side at this cardinality, and it forces an
awkward "lowest common denominator" response shape. I'd only reconsider
this if project counts grow far past "10 or more," which the request's own
numbers don't suggest. **This is a judgment call, flagged explicitly for
review** — if the desired UX is a single sortable-by-RA table interleaving
both types row-by-row (not two sections), the client-side merge still
works, it just does the interleave in JS instead of SQL.

### 3.2 Backend additions (small)

- `projects` list/detail: add a computed `subframes_remaining` /
  `is_complete` field (derivable from existing `count`/`goal_count`, no
  schema change) so the UI doesn't have to recompute completion client-side
  per subframe.
- Wire `priority` (§2) into `task-add`/`task-update`/`tasks` list
  sort options, and into `ProjectCreateSchema`/`ProjectUpdateSchema`, if
  adopted.
- No change needed to the core CRUD — `task-add`, `task-update`,
  `task-get`, `/tasks`, `/projects*` already cover it.

### 3.3 Web UI

- Rework the existing `tasks` + `projects-list` components into one
  "Observation Planning" screen (nav grouping), sections for tasks and
  projects as above, filters (scope, user, state/completion, object name),
  existing `MatTableModule`/`MatSort`/`MatPaginator` pattern reused.
- Task deletion: there is currently no delete path (§0). Decide during
  implementation whether "delete" means a hard DB delete or `state=-1`
  (soft delete) — the `states` table already has a `-1 DELETED` row that
  nothing currently uses.

---

## 4. Component 2 — Night Plan

**Goal**: read-only (mostly), telescope+date parameterized, used by both
the web client and the runner; "multiple discriminating factors,"
"expensive checks" solved the way `hevelius asteroid visible` does it.

### 4.1 Remove the leftover

`hevelius/api/routes/tasks.py:_get_night_plan` (lines ~595–673) is deleted
outright and replaced — it doesn't do visibility filtering at all (§0), so
there's nothing worth preserving. It moves out of `tasks.py` into its own
`hevelius/api/routes/night_plan.py` (that file's docstring literally says
"Task, night-plan, and version API routes" — three unrelated concerns in
one file; splitting it is a small, uncontroversial cleanup while we're in
there). `NightPlanRequestSchema`/response schemas get replaced with the
richer shape in §4.4. `tests/test_api.py`'s existing
`test_night_plan_*` tests (lines 596–813) get rewritten for the new
contract — they currently assert the old date/state-only behavior.

The web `NightPlanComponent`/`NightPlanService` (§0) get rewritten against
the new contract: real telescope selector (default from
`users/me/preferences.default_scope`, per the request — "honour the user
preferences... but the API must allow using any scope," which the query
param already does since `scope_id` stays a required, explicit parameter,
independent of any user's preference), a date picker, and rendering of the
visibility metadata below.

The runner-side leftover (`TaskManager`/`prepare_sequence_file`, the `run`
loop) is **not touched in this session** (out of scope, per the request)
but is flagged here for the record: it's dead/mismatched code per the
runner's own `AGENTS.md`, and will need a rewrite against the contract in
§4.4/§5 in a future runner-focused session.

### 4.2 Shared observability engine

Extract the reusable astronomy primitives out of `hevelius/asteroid.py`
into `hevelius/night.py` (pure refactor, no behavior change for the
asteroid feature — same functions, just importable elsewhere):

- `get_night_times(location, obs_time) -> (sunset, sunrise)` (was
  `_get_night_times`)
- `moon_rise_set(location, night_start, night_end)`
- `moon_separation_deg(ra_deg, dec_deg, time, location)`
- `moon_illumination_pct(time)`
- `sun_altitude_deg(time, location)`
- `transit_altitude_deg(dec_deg, lat_deg)` — `90 − |lat − dec|`
- `ha_window_visible(ra_deg, dec_deg, lat_deg, lst_mid_deg, night_half_h, alt_min_deg)`
  (was `_night_visible`)

Then a new `hevelius/observability.py` with the actual staged pipeline,
operating on generic `(ra_deg, dec_deg, constraints)` — deliberately
**not** task/project-specific, so both this and (optionally, later) an
`asteroid`-style CLI command for tasks/projects can share it:

```
Stage 0 (SQL, cheap, big rejection rate):
  scope_id match; state IN (1,3) for tasks / active+incomplete subframes
  for projects; decl within telescope.min_dec/max_dec; date window
  (skip_before/skip_after, or start_date/end_date) brackets the night;
  for project subframes, filter_id must be in telescope_filters for scope.

Stage 1 (one subtraction, per item):
  alt_max = 90 - |lat - dec|; reject if below the item's effective min_alt.

Stage 2 (trig, no frame transform):
  night hour-angle overlap — does the object spend any time above
  min_alt during the *actual* sunset->sunrise window (not the item's own
  sun-altitude constraint yet)?

Stage 3 (representative-moment check, survivors only):
  pick a check time = transit time if it falls inside the night window,
  else astronomical midnight (mirrors asteroid.py's transit-refinement
  logic). At that moment: sun altitude vs item's max_sun_alt, moon
  separation vs item's moon_distance, moon illumination vs
  item's max_moon_phase.

Stage 4 (precise AltAz, survivors only):
  real astropy GCRS->AltAz transform to confirm altitude/azimuth for the
  response payload.
```

At the scale involved (thousands of tasks + tens of project-subframe rows
per scope — nowhere near the ~1M-row asteroid catalogue), raw performance
of a full 4-stage pass per request is not a real concern; the staged
structure is adopted for **consistency and correctness discipline** (cheap
filters first, exact math only for survivors, one shared place all the
sun/moon/altitude formulas live) rather than because a naive approach would
be too slow. No caching layer in v1 — computed on demand, so a task edited
five minutes before the runner asks is reflected immediately; revisit only
if profiling says otherwise.

**Scoping note**: v1 answers "is this doable at some point tonight, and
roughly when" (one representative check moment), not "what is the full
valid start/end interval." A full interval sweep is a natural v1.1
enhancement once real sequencing needs it (§8).

### 4.3 A concrete, valuable addition: explain mode

Without a way to see *why* something didn't make the cut, users will file
confused bug reports every time a target silently doesn't show up. Add
`?explain=true`: the response includes an `excluded` list alongside
`items`, each tagged with a reason code:

`outside_mount_dec_range`, `below_min_altitude`, `sun_too_high`,
`moon_too_close`, `moon_phase_too_bright`, `outside_date_window`,
`filter_not_on_scope`, `already_complete`, `wrong_state`,
`min_interval_not_elapsed`.

### 4.4 API

`GET`/`POST /api/night-plan` (keeping both verbs, matching the existing
GET+POST-for-the-same-semantics pattern already used elsewhere in this
codebase, e.g. `TasksResource`):

Query/body: `scope_id` (required, always explicit — this is the "API must
allow any scope" requirement), `date` (optional, default = current night
per §1.1 using the scope's own time zone), `user_id` (optional filter,
kept for parity with today), `explain` (optional bool).

```jsonc
{
  "scope_id": 3,
  "night_date": "2026-08-03",
  "night_start_utc": "2026-08-03T19:42:00Z",   // sunset
  "night_end_utc":   "2026-08-04T04:58:00Z",   // sunrise
  "moonrise_utc": "...", "moonset_utc": "...", "moon_illumination_pct": 12,
  "generated_at": "2026-08-03T18:00:11Z",
  "items": [
    {
      "kind": "task",
      "task": { /* existing Task schema */ },
      "visibility": {
        "check_time_utc": "2026-08-03T23:10:00Z",
        "altitude_deg": 47.2, "azimuth_deg": 210.1,
        "moon_separation_deg": 55.3, "sun_altitude_deg": -18.4
      }
    },
    {
      "kind": "project",
      "project": { /* Project schema, subframes filtered to pending ones only */ },
      "visibility": { /* same shape */ }
    }
  ],
  "excluded": [ /* only present when explain=true */
    { "kind": "task", "task_id": 512, "reason": "moon_too_close" }
  ]
}
```

Also add a CLI counterpart, `hevelius night-plan show --scope X --date Y`,
matching the existing convention that most API features have a CLI twin
(`asteroid visible`, `asteroid show --telescope`) — cheap to add since the
module already computes everything, and valuable for debugging without
going through the UI.

---

## 5. Component 3 — Runner support (contract only)

Per the request, runner-side implementation is out of scope for this
session. What *is* in scope: designing a stable contract now, and building
the backend half of it, so a future runner-focused session has a real spec
instead of having to reverse-engineer intent — and because this piece is
also the statistics foundation (§7), it's worth landing independent of the
runner.

### 5.1 The gap: no execution event log

Today, "reporting completion" means two different, weak things:

- For tasks: one atomic `task-update` (`state=6`, `imagename=...`) — a
  single terminal write, no record of actual captured exposure time,
  success/failure detail, or quality metrics.
- For projects: `PATCH /projects/{id}/subframes/{id}` where the **caller
  supplies the new absolute `count`**. This is racy (two writers, or a
  runner that crashes mid-session and miscounts on restart, corrupt the
  number silently) and leaves zero history — you can see *that* a subframe
  has 12/20 frames, never *when* they were taken or by which run.

Neither gives statistics (§7) anything to aggregate.

### 5.2 Proposed: `observation_events`, event-sourced counts

```
observation_events
  id, scope_id, user_id,
  task_id NULL, project_id NULL, subframe_id NULL,   -- exactly one of task_id or (project_id[+subframe_id]) set
  filter_id, exposure_time_actual, started_at timestamptz, completed_at timestamptz,
  night_date date,                -- denormalized via §1.1's rule, computed at write time, makes GROUP BY trivial
  status ('success' | 'failed' | 'aborted'), failure_reason text NULL,
  imagename text NULL, fwhm float NULL, hfr float NULL, eccentricity float NULL, guiding_rms float NULL,
  idempotency_key varchar(64) UNIQUE   -- runner-generated; see 5.4
```

One row per captured (or attempted) sub-exposure. `project_subframes.count`
becomes **derived** — either a DB trigger increments it on insert (keeps
the existing column, keeps existing readers working unmodified) or it's
computed as `COUNT(*) FROM observation_events WHERE subframe_id = …` on
read. I'd start with the trigger approach: cheapest migration, and
`PATCH /projects/{id}/subframes/{id}` can stay around for manual
corrections (a human fixing a miscount) without conflicting, as long as
it's documented as "manual override" rather than "the normal write path"
going forward.

### 5.3 New endpoint

`POST /api/observation-events` — one call per captured/attempted
sub-exposure. On success against a `task_id`, this endpoint also performs
the `state → 6`/`imagename` transition (superseding that part of
`task-update`'s role) so the runner has one call to make, not two.

### 5.4 Idempotency

Runner includes a client-generated `idempotency_key` (e.g. a UUID). Server
does insert-or-ignore on conflict. Needed because network retries on a
"did that POST actually land?" timeout must not double-count an exposure —
this is exactly the kind of bug that's invisible until a cloudy night causes
a burst of retries and your statistics quietly overcount.

### 5.5 Explicitly flagged, not solved here

- **Failure semantics**: what should happen to a task whose exposure fails
  mid-capture (clouds, mount fault)? Proposal: `status=failed` with a
  reason, task stays/returns to state `1` (re-enters the pool) rather than
  being silently lost — but this needs sign-off from whoever runs the
  observatories, it's a behavioral decision, not just a schema one.
- **Auth for unattended operation**: the runner logs in with a real human
  username/password (`APIClient.login`). Workable, but a human-owned
  password used by a 24/7 unattended process is an operational smell
  (rotation, "whose account is this," blast radius on compromise). A
  per-telescope API key/service-account is a reasonable future hardening
  step — not blocking a first version, but worth deciding before "no
  manual actions" is taken literally.
- **Runner liveness**: not part of the four requested components, but
  directly relevant to "long term goal: no manual actions" — the backend
  currently has no idea whether a runner is online, stuck, or has been
  silent for six hours. A lightweight heartbeat
  (`POST /api/scopes/{id}/heartbeat` or similar) is worth a line item in
  whatever session actually builds runner automation.

---

## 6. Component 4 — Statistics

### 6.1 What to build

`observation_events` (§5.2) is the fact table. It directly answers every
metric in the request:

| Requested metric | Query shape |
|---|---|
| Observing time per night | `SUM(exposure_time_actual) WHERE status='success' GROUP BY night_date, scope_id` |
| Tasks completed | `COUNT(*)` of task-linked events with `status='success'`, grouped by `night_date` |
| Time for tasks vs. projects | same `GROUP BY`, split on `task_id IS NOT NULL` |
| (bonus, cheap to add) | per-filter breakdown, per-user breakdown, success/failure rate (frames lost to weather/faults is an operationally useful number), per-telescope utilization |

A couple of canned REST endpoints for the web app's own widgets
(`GET /api/stats/nightly?scope_id&from&to`), computed with plain SQL
aggregates over `observation_events` — no rollup table needed at this
volume (10 telescopes × maybe a few hundred exposures/night, worst case,
is tens of thousands of rows a year; trivial for Postgres to aggregate on
the fly). A nightly rollup/materialized view is worth adding later *if*
dashboard query latency ever becomes a real complaint — not before.

**Scope-reduction point**: don't try to pre-build a REST endpoint for every
conceivable Grafana panel. Grafana's Postgres data source runs arbitrary
read-only SQL directly — anything beyond the couple of in-app widgets can
just be a SQL query written in a Grafana panel against `observation_events`
(or a rollup view later), with zero new backend code.

### 6.2 The database question, part 1: `observation_events` itself

For the business/event data described in §6.1 alone, the original
reasoning still holds: ≤10 telescopes, thousands-to-tens-of-thousands of
rows a year, dimensional data that wants to join against `tasks`,
`projects`, `users`, `filters`. That's a plain Postgres table, no argument.
The picture changes once a second, genuinely different data class enters —
see below.

### 6.3 The database question, part 2: external telemetry changes the answer

You're right that weather, roof open/closed, sensor temperatures, and
ASCOM telescope state are a different data class than `observation_events`,
and I was implicitly scoping the earlier recommendation to the latter only.
Characterizing the difference concretely:

| | `observation_events` | Telemetry (weather / roof / sensors / ASCOM) |
|---|---|---|
| Frequency | one row per exposure (minutes apart) | continuous polling (seconds-to-minutes) |
| Channels | few, fixed dimensions | many numeric channels per telescope, growing over time |
| Primary use | exact audit trail, joined to tasks/projects/users | downsampled graphs, threshold alerting, coarse long-term history |
| Retention shape | keep every row forever (it's the audit trail) | keep fine detail briefly, coarse rollups long-term |

That last row is the important one: telemetry *wants* automatic
downsampling and retention management (raw 10-second samples for 90 days,
5-minute rollups forever) — machinery you'd otherwise hand-roll as cron
jobs in plain Postgres. That's a legitimate, different requirement, and it
changes which of the earlier options make sense — re-evaluated against
*this* data class specifically:

| Option | Fit for telemetry | Why / why not |
|---|---|---|
| **TimescaleDB (recommended)** | ✅ | Postgres extension: hypertables auto-partition by time, continuous aggregates auto-maintain rollups, retention policies auto-expire raw data — the exact machinery this data needs, declared in SQL, no external service. Stays in the same database as `observation_events`, so **correlating a failed/aborted exposure with cloud cover or roof state at that moment is a plain SQL join**, not a cross-database federation — directly useful for diagnosing "was this actually a weather abort?" (§8 flags live weather *gating* as still unsolved; this at least closes the post-hoc analysis half of that gap). One backup job, one credential story, one system to run. |
| **Plain PostgreSQL (no Timescale)** | ⚠️ works, but you'd rebuild Timescale by hand | Postgres can absolutely store this volume, but continuous high-frequency polling from up to 10 sites, over months/years, with no automatic partitioning/rollup/retention, means either unbounded table growth or a hand-written downsampling+deletion job — exactly what Timescale gives you for free as a config statement. Since Timescale is "the same Postgres, plus an extension," there's no real reason to decline it once this data class exists. |
| **InfluxDB** | ⚠️ legitimate, second-choice | A real, popular, self-hostable, Grafana-native option, and this data class is actually within its intended envelope (unlike the earlier `observation_events` case). The reason to prefer Timescale over it here is architectural fit, not capability: it'd be a second database (separate backup/ops/credentials) and, more concretely, a second **ingestion path** — see below, telemetry is naturally pushed by the runner over the same authenticated HTTPS API it already uses, and Influx doesn't change that story, it just adds a second target for it to write to. Worth revisiting if telemetry cardinality/volume ever outgrows what one Postgres+Timescale instance handles comfortably (unlikely at 10 telescopes, but not impossible at much larger fleet sizes). |
| **Prometheus** | ⚠️ good fit for a *different* job | Prometheus's pull/scrape model is a real mismatch for this topology: it wants to reach into each site and scrape a `/metrics` endpoint, and "multiple locations" plausibly means home-observatory setups behind NAT with no inbound access — you'd need a Pushgateway workaround to make pull-based collection work at all. Where Prometheus *is* the right tool: monitoring the **machines** themselves (is the backend server up, is a runner PC's disk full, is the API responding) — that's a separate, complementary concern from domain telemetry (roof/weather/mount state) and shouldn't be conflated with it. If infra monitoring is wanted later, it can run alongside Timescale-backed domain telemetry as two independent, non-competing systems. |

**Revised recommendation**: enable the **TimescaleDB extension on the same
Postgres instance**, and use it for telemetry hypertables (§6.4) while
`observation_events` and everything else stays exactly as designed in §6.2
— one database, two workloads it's each well-suited for, rather than
fragmenting into Postgres + InfluxDB + Prometheus for three overlapping
concerns. Point Grafana at that one Postgres/Timescale instance for
everything (Grafana's Postgres data source understands Timescale
hypertables/continuous-aggregates transparently — no separate data source
needed).

### 6.4 Telemetry schema and ingestion (sketch)

Not every telemetry source is actually high-frequency — worth not
cargo-culting "hypertable" onto all of it:

- **Roof state** is naturally sparse (a handful of open/close transitions a
  night) — an event log, same shape as `observation_events`, not a
  hypertable candidate:
  ```
  telemetry_roof_events (time timestamptz, scope_id int, state ('open'|'closed'|'moving'|'error'), reason text NULL)
  ```
- **Weather**, **sensor temperatures**, and **ASCOM state** genuinely are
  continuous polls and become hypertables:
  ```
  telemetry_weather      (time, scope_id, source, temperature_c, humidity_pct, wind_speed_kph, cloud_cover_pct, sky_temp_c, rain boolean)
  telemetry_sensor_temps (time, scope_id, sensor, temperature_c)          -- sensor: 'camera_ccd' | 'ambient' | 'mount' | 'focuser' | ...
  telemetry_ascom_state  (time, scope_id, mount_ra_deg, mount_dec_deg, mount_tracking, mount_slewing, focuser_position, filter_wheel_position, connected)
  ```
  Each `SELECT create_hypertable('telemetry_weather', 'time'), ...` plus a
  continuous aggregate (e.g. 5-minute rollups) and a retention policy
  (drop raw rows after ~90 days, keep rollups indefinitely) — a handful of
  SQL statements in the migration, not application code.

  Modeling choice worth flagging: this is a handful of purpose-built,
  typed tables (matching how the rest of Hevelius is modeled — explicit
  columns, not JSONB blobs) rather than one generic long/narrow
  `(time, scope_id, metric, value)` table. That trades a small amount of
  schema flexibility (a genuinely new sensor type needs a migration) for
  real column types and much more natural SQL — the right call while the
  telemetry sources are a known, short list (weather / roof / sensor temps
  / ASCOM). Revisit if the sensor set turns out to be large and
  fast-changing.

- **Ingestion**: reuse the runner's existing authenticated HTTPS
  relationship with the backend rather than inventing a new
  push/pull topology (Prometheus scrape targets or an InfluxDB write
  token) — the runner already polls ASCOM/ambient sensors on the
  observatory PC for its own purposes, so it batches samples and `POST`s
  them periodically (e.g. once a minute, not per-sample) to a new
  `POST /api/telemetry` endpoint. This is push-based by construction, so
  it works from a home-observatory site behind NAT with no inbound
  access, unlike Prometheus's default pull model. **Runner-side polling
  itself is out of scope for this session**, same as the rest of the
  runner work — this section defines the backend contract it will target.

---

## 7. Task breakdown

Numbered `OS-#` ("Observation Scheduler") so each task has one stable
reference distinct from GitHub issue/PR numbers, which are per-repo and
would collide across `hevelius-backend`/`hevelius-web`/`hevelius-runner`
(this plan itself lives under PR #110 in `hevelius-backend`). If/when these
become actual GitHub issues, `OS-#` can go in the issue title as a
cross-repo anchor.

**On "is night identity a good separate task?"** — yes, worth pulling out.
The `night_date(scope, t)` rule (§1.1) is pure logic (not a schema change),
it's small and precisely testable in isolation (the worked examples in
§1.1 basically *are* the test cases), and — most importantly — three
different consumers need to call the exact same function: Night Plan
(OS-4), `observation_events.night_date` (OS-8), and the nightly Statistics
grouping (OS-9). Bundling it into whichever of those three ships first
risks the other two re-deriving it slightly differently later. Written and
tested once, up front, as its own task, that risk goes away. It's listed
separately below (OS-1) rather than folded into the schema task (OS-2),
since OS-2 is schema-only and this is application code.

| ID | Title | Repo | Depends on | Size | Status |
|---|---|---|---|---|---|
| **OS-1** | Night identity (`night_date` computation) | backend | — | S | Planned |
| **OS-2** | Data model: telescopes, projects, tasks | backend | — | M | Planned |
| **OS-3** | Shared observability engine | backend | OS-1, OS-2 | M | Planned |
| **OS-4** | Night Plan API rewrite | backend | OS-3 | M | Planned |
| **OS-5** | Night Plan web UI | web | OS-4 | S–M | Planned |
| **OS-6** | Observation Planning — backend additions | backend | OS-2 | S | Planned |
| **OS-7** | Observation Planning — web UI | web | OS-6 | M–L | Planned |
| **OS-8** | Observation events (execution log) | backend | OS-1, OS-2 | L | Planned |
| **OS-9** | Statistics API | backend | OS-8 | S–M | Planned |
| **OS-10** | Telemetry (weather / roof / sensors / ASCOM) | backend (+ runner, later) | OS-2 | L | **Deferred** — separate topic, per your note |
| **OS-11** | Runner rewrite: night plan + execution reporting | runner | OS-4, OS-8 | L | **Deferred** — separate session, unchanged from the original request |

**OS-1 — Night identity (`night_date` computation).** The §1.1 rule as a
small, independently unit-tested function (e.g. in `hevelius/night.py`,
see OS-3). Logically independent of the DB — takes a tz string as a
parameter — but only useful in anger once OS-2's `telescopes.timezone`
column exists to feed it.

**OS-2 — Data model: telescopes, projects, tasks.** Bundled per your
request — one migration (or tight sequence) covering `telescopes.timezone`;
`projects` observing-constraint columns (`min_alt`, `moon_distance`,
`max_moon_phase`, `max_sun_alt`, `min_interval`) + `priority`; `tasks.priority`;
and the `tasks` naive-`timestamp` → `timestamptz` conversion (§2). Includes
OpenAPI updates for the new/changed fields and the manual timezone backfill
for existing telescope rows (5–10 rows, not automatable from lat/lon
reliably). `observation_events` (OS-8) and telemetry (OS-10) are deliberately
**not** in this task — they're new tables with real design questions
attached, not plain column additions.

**OS-3 — Shared observability engine.** Extract `hevelius/night.py` out of
`hevelius/asteroid.py` (pure refactor, no behavior change for the asteroid
feature) plus the new `hevelius/observability.py` staged-filter pipeline
(§4.2), generic over `(ra_deg, dec_deg, constraints)`. Includes the RA
hours→degrees conversion at the boundary (§1.2) and a unit test guarding
it specifically — the easiest kind of bug to introduce here and the
hardest to notice by inspection.

**OS-4 — Night Plan API rewrite.** New `hevelius/api/routes/night_plan.py`;
delete the old `_get_night_plan` stub out of `tasks.py` (§4.1); new
request/response schemas including `explain=true` (§4.3–4.4); OpenAPI
update; rewritten `test_night_plan_*` tests; `hevelius night-plan show`
CLI companion folded into this task rather than split out, since it's a
thin wrapper over the same module.

**OS-5 — Night Plan web UI.** Rewrite `NightPlanComponent`/
`NightPlanService` against the OS-4 contract: telescope selector defaulted
from `users/me/preferences.default_scope`, date picker, visibility badges,
explain-mode toggle.

**OS-6 — Observation Planning: backend additions.** Computed
`is_complete`/`subframes_remaining` on project list/detail; wire `priority`
(from OS-2) into `task-add`/`task-update`/`tasks` list sort and
project create/update. Small — no new tables, no new endpoints.

**OS-7 — Observation Planning: web UI.** The unified tasks+projects
planning screen (§3.1's client-side-merge recommendation), filters, and
whatever bulk actions turn out to be wanted. Two decisions from §8 land
here and are worth closing out before/during implementation rather than
guessing: the unified-vs-two-sections final call (§3.1), and task-delete
semantics (no delete endpoint exists today — hard delete vs. `state=-1`).

**OS-8 — Observation events (execution log).** `observation_events` table
(§5.2); `POST /api/observation-events` (§5.3) including idempotency-key
handling (§5.4); switch `project_subframes.count` to trigger-derived from
the event log, keeping `PATCH` around as a manual-override path rather than
the primary write path; publish the "Runner Integration Guide" as the spec
OS-11 will implement against. The largest single task here — it's real
schema plus a state-transition change to how subframe counts work.
Decisions flagged in §5.5 (failure/retry semantics, unattended auth) are
worth resolving before or during this task, not deferred silently.

**OS-9 — Statistics API.** `GET /api/stats/nightly` (and similar) as plain
SQL aggregates over `observation_events` (§6.1); example Grafana dashboard
doc pointed directly at Postgres. Depends on OS-8 existing, though it can
be developed and demoed against seed/backfilled data before OS-11 (the
runner) actually produces live events.

**OS-10 — Telemetry (weather / roof / sensors / ASCOM). Deferred**, as
requested — a separate, large topic on its own (external data sources,
TimescaleDB, a new runner-side polling/ingestion story). Kept numbered so
§6.3–6.4's design has a stable reference when it's picked back up, but
intentionally excluded from the active sequence below.

**OS-11 — Runner rewrite: night plan + execution reporting. Deferred** —
unchanged from the original request's scoping. Replaces the dead
`TaskManager`/`run` loop (§0, §4.1) against the OS-4/OS-8 contracts, once
those exist. Listed here only so it isn't lost track of.

### Suggested order

OS-1 and OS-2 have no dependencies and can start immediately, in either
order or in parallel. Once both land: OS-3 → OS-4 → OS-5 is one track
(Night Plan); OS-6 → OS-7 is an independent second track (Observation
Planning) that only needs OS-2, not OS-3/4. OS-8 needs only OS-1 and OS-2,
so it can run alongside either track rather than waiting on Night Plan;
OS-9 follows it. OS-10 and OS-11 stay off the active sequence per above.

---

## 8. Risks, flaws, and omissions (the skeptical pass you asked for)

- **Two execution models, bridged not unified.** Tasks are a one-shot state
  machine; projects are an aggregate goal/count target. This plan keeps
  them structurally distinct (different backend rows, different UI
  sections) and bridges them only where it's cheap to do so: one shared
  visibility engine (§4.2) and one shared event log (§5.2). Don't let a
  future "let's unify tasks and projects into one entity" refactor sneak
  in scope-creep — the request doesn't ask for that, and the two models
  serve genuinely different use cases (single-shot vs. accumulate-until-
  goal).
- **Schema gaps that block a "real" night plan today**: projects have no
  observing constraints, telescopes have no time zone, and the old
  night-plan endpoint doesn't even look at RA/Dec. None of this is
  optional groundwork — the night plan literally cannot be correct without
  §2.
- **`tasks` datetime columns are naive `timestamp`, not `timestamptz`** —
  a latent correctness bug once sites span time zones; low cost to fix now
  (§2), expensive to discover later as a "why did this task activate at
  the wrong time" bug report.
- **No horizon mask.** Both the existing asteroid visibility feature and
  this plan's engine treat the horizon as geometrically flat (0° altitude,
  no airmax/obstruction model). A tree, dome slit limit, or neighboring
  building can make a "visible" target actually unobservable. Worth a
  per-telescope horizon-mask feature eventually; explicitly not in this
  plan.
- **No *live* weather/cloud gating.** This is probably the single biggest
  gap relative to the stated long-term goal ("automate observations, no
  manual actions each evening"). Night Plan answers "what *could* be
  observed tonight" as a static, pre-computed list — it says nothing about
  live sky conditions at the moment of execution. §6.3–6.4 now plans for
  *storing* weather/roof/sensor telemetry, which closes the **post-hoc**
  half of this gap (e.g. "was this abort actually caused by clouds?" is a
  SQL join once telemetry lands) — but storing telemetry is not the same
  as a live go/no-go gate the runner consults *during* the night before/
  while executing. That decision logic is still separate, still
  unaddressed, and still runner-side future work. Flagging this explicitly
  so telemetry storage isn't mistaken for automation gating.
- **No ordering/scheduling, only filtering.** Night Plan (v1, per §4.2's
  scoping note) tells you *what's possible*, not *what order to shoot it
  in*. Real sequencing — meridian flips, filter-change cost, optimizing for
  transit time across many targets in one night — is a genuinely harder
  scheduling problem. It's reasonable to lean on NINA's own
  sequencer/scheduler for this in the near term and treat a backend "smart
  sequencer" as an explicit, separate future phase — but don't let "Night
  Plan" quietly become the thing people expect to solve sequencing; it
  doesn't, on purpose, in v1.
- **No access control beyond a flat permission bitmask.** Any authenticated
  user can currently submit tasks/projects to any `scope_id` and read any
  telescope's night plan. Fine for one trusted team; "multiple observatory
  owners" sharing one deployment is exactly the scenario where that stops
  being fine (private allocations, who can queue time on whose telescope).
  Not blocking a first internal rollout, but decide this before opening
  the system to more than one owner.
- **Unattended auth uses a human account/password** (§5.5) — a hardening
  gap, not a blocker.
- **No idempotency today anywhere in the write API** — every existing
  POST/PATCH assumes exactly-once delivery. `observation-events` gets an
  idempotency key (§5.4) because it's new and it's obviously needed there;
  the same gap exists on `task-update`/subframe `PATCH` today and is out of
  scope to retrofit here.
- **`min_interval`'s exact intended semantics are unclear.** It exists on
  `tasks` (and would be mirrored onto `projects` per §2), but nothing in
  the current codebase enforces it, and it isn't obvious from the schema
  alone whether it means "don't resurface within N seconds of last
  `performed`" or something else (e.g., variable-star cadence). Confirm the
  intended meaning with whoever actually uses it before the new engine
  starts enforcing it — better to ask than to guess and silently change
  behavior for existing tasks that set it.
- **Scale check, stated explicitly so nobody over-builds**: 10 telescopes,
  thousands of tasks, tens of projects, a few hundred exposure-events/night
  at the high end (continuous telemetry per §6.3–6.4 is higher-frequency
  but still modest — tens of channels × 10 sites polled every 10–60s). This
  does not justify message queues, Redis caches, a genuinely separate
  database system (InfluxDB/Prometheus), or a distributed scheduler — note
  that TimescaleDB is deliberately *not* in that list, since it's an
  extension to the one Postgres instance already being run, not a second
  system to operate. Every recommendation above is sized for "small
  self-hosted system," not "cloud-scale" — if a future reviewer proposes
  infrastructure beyond what's here, ask what problem it solves at *this*
  scale first.

---

## 9. Recap: answers to your specific questions

1. **Does the plan make sense?** Directionally yes — backlog (Planning) →
   nightly filtered subset (Night Plan) → execution + reporting (Runner) →
   event log → aggregated Statistics is a sound pipeline, and it matches
   how the codebase already thinks about tasks/projects. The concrete
   blockers are schema gaps (§2) and the missing event log (§5.2), both
   addressed above; the concrete risks are the automation-adjacent gaps in
   §8 (weather, ACLs, unattended auth, sequencing) that this plan
   deliberately does not attempt to solve, so they don't get assumed-solved
   by omission.
2. **Night-date convention**: adopted NINA's "local time − 12h, take the
   date" rule exactly, detailed with a worked example in §1.1. The one
   addition beyond NINA's own approach is a per-telescope IANA time zone,
   which NINA doesn't need (single PC, single system clock) but this
   multi-site system does.
3. **Naming**: settled — "Observation Planning," "Night Plan," and
   **"runner"** stay as the formal names (§1.3).
4. **Skeptical review**: §8, in full.

---

## Appendix: example `observation-events` POST payload

```jsonc
POST /api/observation-events
{
  "scope_id": 3,
  "task_id": 512,                 // XOR project_id/subframe_id
  "filter_id": 7,
  "exposure_time_actual": 300.0,
  "started_at": "2026-08-03T23:05:00Z",
  "completed_at": "2026-08-03T23:10:00Z",
  "status": "success",
  "imagename": "obs3/2026/08/m33_300s_0007.fits",
  "fwhm": 2.1, "hfr": 1.9, "eccentricity": 0.12,
  "idempotency_key": "b3f1c2a0-…"
}
```

## Appendix: example `POST /api/telemetry` payload

Batched, not one request per sample — the runner accumulates a minute (or
so) of polled readings and sends them together.

```jsonc
POST /api/telemetry
{
  "scope_id": 3,
  "weather": [
    { "time": "2026-08-03T23:00:00Z", "source": "boltwood", "temperature_c": 9.1,
      "humidity_pct": 62, "wind_speed_kph": 8.4, "cloud_cover_pct": 5, "sky_temp_c": -18.2, "rain": false },
    { "time": "2026-08-03T23:01:00Z", "source": "boltwood", "temperature_c": 9.0,
      "humidity_pct": 63, "wind_speed_kph": 9.1, "cloud_cover_pct": 5, "sky_temp_c": -18.0, "rain": false }
  ],
  "sensor_temps": [
    { "time": "2026-08-03T23:00:00Z", "sensor": "camera_ccd", "temperature_c": -10.0 },
    { "time": "2026-08-03T23:00:00Z", "sensor": "ambient", "temperature_c": 9.1 }
  ],
  "ascom_state": [
    { "time": "2026-08-03T23:00:30Z", "mount_ra_deg": 45.2, "mount_dec_deg": 25.9,
      "mount_tracking": true, "mount_slewing": false, "focuser_position": 12480,
      "filter_wheel_position": 3, "connected": true }
  ],
  "roof_events": [
    { "time": "2026-08-03T19:40:00Z", "state": "open", "reason": "schedule-start" }
  ]
}
```
