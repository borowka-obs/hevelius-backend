"""
Night plan computation (OS-4, #46).

Answers "what can this telescope actually observe on the night of <date>",
for both tasks and projects, and - in explain mode - why everything else was
left out.

This is the module both the `/api/night-plan` endpoint
(`hevelius/api/routes/night_plan.py`) and the `hevelius night-plan show` CLI
command (`hevelius/cli/night_plan.py`) call; neither contains any planning
logic of its own.

Staging (doc/observation-scheduler-plan.md §4.2): stage 1 is the SQL/Python
pre-filter implemented here - it is inherently table-specific (tasks and
projects have different notions of "still worth observing"), which is why
`hevelius/observability.py` deliberately does not own it. Stages 2-5 (the
astronomy: transit altitude, night hour-angle overlap, sun/moon at a
representative moment, precise AltAz confirm) live in `observability.py` and
run only on rows that survive stage 1.

Ordering: `priority` descending first (the ordering signal added in OS-2),
then tasks before projects, then newest id first - the same "highest priority,
most recently added" order the old endpoint produced for tasks alone.
"""

import datetime
import logging
import time as time_module
from dataclasses import dataclass
from typing import List, Optional
from zoneinfo import ZoneInfo

from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy import units as u

from hevelius import db, night, observability
from hevelius.observability import Constraints

logger = logging.getLogger(__name__)

# Task states worth planning: 1 NEW and 3 IN QUEUE. 2 (ACTIVATED) and 4
# (EXECUTED) are legacy states nothing in the API sets any more, 6 is DONE,
# 0/-1/-2 are templates and soft-deletes.
PLANNABLE_TASK_STATES = (1, 3)

# Stage-1 exclusion reasons (doc/observation-scheduler-plan.md §4.3). The
# astronomy reasons (below_min_altitude, sun_too_high, moon_too_close,
# moon_phase_too_bright) are raised by hevelius/observability.py instead.
REASON_WRONG_STATE = "wrong_state"
REASON_OUTSIDE_DATE_WINDOW = "outside_date_window"
REASON_OUTSIDE_MOUNT_DEC_RANGE = "outside_mount_dec_range"
REASON_FILTER_NOT_ON_SCOPE = "filter_not_on_scope"
REASON_ALREADY_COMPLETE = "already_complete"
# Not in the plan's original list, but tasks.ra/decl and projects.ra/decl are
# both nullable and a target with no coordinates can't be checked at all.
REASON_MISSING_COORDINATES = "missing_coordinates"

# `min_interval_not_elapsed` from §4.3 is deliberately not raised yet: with no
# execution event log (OS-8) there is nothing to measure the interval since.


class NightPlanError(Exception):
    """
    A caller error (unknown telescope, telescope not configured for planning).

    Carries the HTTP status the API layer should turn it into; the CLI just
    prints the message.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Telescope:
    """The telescope columns night planning needs."""
    scope_id: int
    name: str
    lat: float
    lon: float
    alt: float
    min_dec: Optional[float]
    max_dec: Optional[float]
    timezone: str

    def location(self) -> EarthLocation:
        """astropy observing location for this site."""
        return EarthLocation(
            lat=self.lat * u.deg,  # pylint: disable=no-member
            lon=self.lon * u.deg,  # pylint: disable=no-member
            height=(self.alt or 0.0) * u.m,  # pylint: disable=no-member
        )


@dataclass
class Candidate:
    """
    One task or project that survived stage 1, ready for the visibility engine.

    `payload` is the serialized task/project dict returned to the client;
    everything else is what the staged pipeline and the final sort need.
    """
    kind: str
    ident: int
    label: str
    ra_deg: float
    dec_deg: float
    constraints: Constraints
    priority: int
    payload: dict


@dataclass
class _Rejected:
    """A stage-1 or stage-2..5 rejection, reported only when explain=True."""
    kind: str
    ident: int
    label: str
    reason: str


def _as_utc(value):
    """Normalize a DB timestamp to an aware UTC datetime (naive == UTC)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _as_date(value):
    """Normalize a DB date/timestamp column to a plain date."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    return value


def _iso_utc(value) -> Optional[str]:
    """Format an astropy Time (or datetime) as a whole-second ISO-8601 UTC string."""
    if value is None:
        return None
    if isinstance(value, Time):
        moment = value.utc.to_datetime()
    else:
        moment = _as_utc(value).replace(tzinfo=None)
    return moment.replace(microsecond=0).isoformat() + "Z"


def _fetch_telescope(cnx, scope_id: int) -> Telescope:
    rows = db.run_query(
        cnx,
        """SELECT scope_id, name, lat, lon, alt, min_dec, max_dec, timezone
           FROM telescopes WHERE scope_id = %s""",
        (scope_id,),
    )
    if not rows:
        raise NightPlanError(f"Telescope {scope_id} not found.", status=404)

    scope_id, name, lat, lon, alt, min_dec, max_dec, timezone = rows[0]
    if lat is None or lon is None:
        raise NightPlanError(
            f"Telescope {scope_id} has no location (lat/lon) configured.", status=400)

    timezone = timezone or "UTC"
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # noqa: BLE001 - any zoneinfo failure is a config error
        raise NightPlanError(
            f"Telescope {scope_id} has an invalid timezone {timezone!r}: {exc}", status=400
        ) from exc

    return Telescope(scope_id=scope_id, name=name, lat=float(lat), lon=float(lon),
                     alt=float(alt or 0.0), min_dec=min_dec, max_dec=max_dec,
                     timezone=timezone)


def _dec_out_of_mount_range(scope: Telescope, dec_deg: float) -> bool:
    """Is this declination outside the mount's reachable range?"""
    if scope.min_dec is not None and dec_deg < scope.min_dec:
        return True
    return scope.max_dec is not None and dec_deg > scope.max_dec


# aavso_id is the observer's, on users - the old endpoint picked it up unqualified
# from its implicit tasks/users join, which read as if it were a task column.
_TASK_COLUMNS = """t.task_id, t.user_id, u.login, t.scope_id, u.aavso_id, t.object, t.ra, t.decl,
    t.exposure, t.descr, t.filter, t.binning, t.guiding, t.dither, t.calibrate, t.solve,
    t.other_cmd, t.min_alt, t.moon_distance, t.skip_before, t.skip_after, t.min_interval,
    t.comment, t.state, t.imagename, t.created, t.activated, t.performed, t.max_moon_phase,
    t.max_sun_alt, t.auto_center, t.calibrated, t.solved, t.sent, t.priority"""


def _task_row_to_dict(row, scope_name):
    (task_id, user_id, user_login, scope_id, aavso_id, obj, ra, decl, exposure, descr,
     filter_name, binning, guiding, dither, calibrate, solve, other_cmd, min_alt,
     moon_distance, skip_before, skip_after, min_interval, comment, state, imagename,
     created, activated, performed, max_moon_phase, max_sun_alt, auto_center, calibrated,
     solved, sent, priority) = row
    return {
        "task_id": task_id, "user_id": user_id, "user_login": user_login,
        "scope_id": scope_id, "scope_name": scope_name, "aavso_id": aavso_id,
        "object": obj, "ra": ra, "decl": decl, "exposure": exposure, "descr": descr,
        "filter": filter_name, "binning": binning, "guiding": bool(guiding),
        "dither": bool(dither), "calibrate": bool(calibrate), "solve": bool(solve),
        "other_cmd": other_cmd, "min_alt": min_alt, "moon_distance": moon_distance,
        "skip_before": skip_before, "skip_after": skip_after, "min_interval": min_interval,
        "comment": comment, "state": state, "imagename": imagename, "created": created,
        "activated": activated, "performed": performed, "max_moon_phase": max_moon_phase,
        "max_sun_alt": max_sun_alt, "auto_center": bool(auto_center),
        "calibrated": bool(calibrated), "solved": bool(solved), "sent": bool(sent),
        "priority": priority,
    }


def _task_exclusion_reason(task, scope: Telescope, night_start: datetime.datetime,
                           night_end: datetime.datetime):
    """
    Stage 1 for a task: the reason it can't be planned tonight, or None.

    This is the authoritative version of the check. `_collect_tasks` pushes the
    same conditions into SQL when not explaining, purely so the common case
    doesn't drag every task of the telescope out of the database - the verdict
    itself is always made here.
    """
    if task["state"] not in PLANNABLE_TASK_STATES:
        return REASON_WRONG_STATE

    skip_before = _as_utc(task["skip_before"])
    skip_after = _as_utc(task["skip_after"])
    if skip_before is not None and skip_before > night_end:
        return REASON_OUTSIDE_DATE_WINDOW
    if skip_after is not None and skip_after < night_start:
        return REASON_OUTSIDE_DATE_WINDOW

    if task["ra"] is None or task["decl"] is None:
        return REASON_MISSING_COORDINATES

    if _dec_out_of_mount_range(scope, task["decl"]):
        return REASON_OUTSIDE_MOUNT_DEC_RANGE

    return None


def _collect_tasks(cnx, scope: Telescope, night_start: Time, night_end: Time,
                   user_id: Optional[int], explain: bool, rejected: List[_Rejected]):
    """Fetch tasks for the telescope and split them into candidates and stage-1 rejects."""
    night_start_dt = night_start.utc.to_datetime(timezone=datetime.timezone.utc)
    night_end_dt = night_end.utc.to_datetime(timezone=datetime.timezone.utc)

    query = f"""SELECT {_TASK_COLUMNS}
                FROM tasks t JOIN users u ON t.user_id = u.user_id
                WHERE t.scope_id = %s"""
    values = [scope.scope_id]

    if user_id is not None:
        query += " AND t.user_id = %s"
        values.append(user_id)

    if not explain:
        # Cheap pre-filter, mirroring _task_exclusion_reason. Skipped in explain
        # mode so the excluded list can name the rows this would have dropped.
        query += " AND t.state IN %s"
        values.append(tuple(PLANNABLE_TASK_STATES))
        query += """ AND (t.skip_before IS NULL OR t.skip_before <= %s)
                     AND (t.skip_after IS NULL OR t.skip_after >= %s)
                     AND t.ra IS NOT NULL AND t.decl IS NOT NULL"""
        values.extend([night_end_dt, night_start_dt])
        if scope.min_dec is not None:
            query += " AND t.decl >= %s"
            values.append(scope.min_dec)
        if scope.max_dec is not None:
            query += " AND t.decl <= %s"
            values.append(scope.max_dec)

    query += " ORDER BY t.priority DESC, t.task_id DESC"

    candidates = []
    for row in db.run_query(cnx, query, values) or []:
        task = _task_row_to_dict(row, scope.name)
        reason = _task_exclusion_reason(task, scope, night_start_dt, night_end_dt)
        if reason is not None:
            if explain:
                rejected.append(_Rejected(
                    kind="task", ident=task["task_id"], label=task["object"], reason=reason))
            continue
        candidates.append(Candidate(
            kind="task",
            ident=task["task_id"],
            label=task["object"],
            ra_deg=observability.ra_hours_to_deg(task["ra"]),
            dec_deg=task["decl"],
            constraints=Constraints(
                min_alt=task["min_alt"], moon_distance=task["moon_distance"],
                max_moon_phase=task["max_moon_phase"], max_sun_alt=task["max_sun_alt"]),
            priority=task["priority"] or 0,
            payload=task,
        ))
    return candidates


_PROJECT_COLUMNS = """p.project_id, p.name, p.description, p.regexps, p.scope_id, p.ra, p.decl,
    p.active, p.last_updated, p.total_integration_time, p.start_date, p.end_date,
    p.publications, p.rotation, p.focal, p.resx, p.resy, p.pixel_x, p.pixel_y,
    p.min_alt, p.moon_distance, p.max_moon_phase, p.max_sun_alt, p.min_interval, p.priority"""


def _project_row_to_dict(row):
    (project_id, name, description, regexps, scope_id, ra, decl, active, last_updated,
     total_integration_time, start_date, end_date, publications, rotation, focal, resx,
     resy, pixel_x, pixel_y, min_alt, moon_distance, max_moon_phase, max_sun_alt,
     min_interval, priority) = row
    start_date = _as_date(start_date)
    end_date = _as_date(end_date)
    return {
        "project_id": project_id, "name": name, "description": description,
        "regexps": regexps, "scope_id": scope_id, "ra": ra, "decl": decl,
        "active": bool(active), "last_updated": last_updated,
        "total_integration_time": float(total_integration_time) if total_integration_time is not None else 0.0,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "publications": publications, "rotation": rotation, "focal": focal,
        "resx": resx, "resy": resy, "pixel_x": pixel_x, "pixel_y": pixel_y,
        "min_alt": min_alt, "moon_distance": moon_distance,
        "max_moon_phase": max_moon_phase, "max_sun_alt": max_sun_alt,
        "min_interval": min_interval, "priority": priority,
        "subframes": [], "user_ids": [],
        # Not DB columns: raw dates kept for the stage-1 window check below.
        "_start_date": start_date, "_end_date": end_date,
    }


def _subframe_pending(subframe) -> bool:
    """
    Is there anything left to shoot for this subframe?

    Inactive subframes never count. A NULL goal_count means "no target set",
    which is treated as open-ended rather than complete - a project nobody has
    given a goal to is still something the telescope can work on.
    """
    if not subframe["active"]:
        return False
    if subframe["goal_count"] is None:
        return True
    return (subframe["count"] or 0) < subframe["goal_count"]


def _fetch_subframes(cnx, project_ids):
    """Subframes of the given projects, grouped by project_id."""
    if not project_ids:
        return {}
    rows = db.run_query(
        cnx,
        """SELECT s.id, s.project_id, s.filter_id, f.short_name, f.full_name, f.url, f.active,
                  s.exposure_time, s.count, s.goal_count, s.active, s.last_updated
           FROM project_subframes s
           LEFT JOIN filters f ON f.filter_id = s.filter_id
           WHERE s.project_id IN %s
           ORDER BY s.id""",
        (tuple(project_ids),),
    )
    by_project = {}
    for (sub_id, project_id, filter_id, short_name, full_name, url, filter_active,
         exposure_time, count, goal_count, active, last_updated) in rows or []:
        by_project.setdefault(project_id, []).append({
            "id": sub_id, "project_id": project_id, "filter_id": filter_id,
            "filter": None if filter_id is None else {
                "filter_id": filter_id, "short_name": short_name,
                "full_name": full_name, "url": url, "active": bool(filter_active),
            },
            "exposure_time": exposure_time, "count": count or 0, "goal_count": goal_count,
            "active": bool(active), "last_updated": last_updated,
        })
    return by_project


def _fetch_project_users(cnx, project_ids):
    """user_ids of the given projects, grouped by project_id."""
    if not project_ids:
        return {}
    rows = db.run_query(
        cnx,
        "SELECT project_id, user_id FROM project_users WHERE project_id IN %s ORDER BY user_id",
        (tuple(project_ids),),
    )
    by_project = {}
    for project_id, user_id in rows or []:
        by_project.setdefault(project_id, []).append(user_id)
    return by_project


def _scope_filter_ids(cnx, scope_id):
    rows = db.run_query(
        cnx, "SELECT filter_id FROM telescope_filters WHERE scope_id = %s", (scope_id,))
    return {r[0] for r in rows or []}


def _project_exclusion_reason(project, scope: Telescope, night_date: datetime.date):
    """Stage 1 for a project, excluding the subframe checks (which need extra queries)."""
    if not project["active"]:
        return REASON_WRONG_STATE

    if project["_start_date"] is not None and project["_start_date"] > night_date:
        return REASON_OUTSIDE_DATE_WINDOW
    if project["_end_date"] is not None and project["_end_date"] < night_date:
        return REASON_OUTSIDE_DATE_WINDOW

    if project["ra"] is None or project["decl"] is None:
        return REASON_MISSING_COORDINATES

    if _dec_out_of_mount_range(scope, project["decl"]):
        return REASON_OUTSIDE_MOUNT_DEC_RANGE

    return None


def _subframe_exclusion_reason(pending, on_scope):
    """
    Stage 1 for a project's subframes.

    `already_complete` when nothing is pending at all; `filter_not_on_scope`
    when the only pending work needs filters this telescope doesn't carry.
    """
    if not pending:
        return REASON_ALREADY_COMPLETE
    if not on_scope:
        return REASON_FILTER_NOT_ON_SCOPE
    return None


def _collect_projects(cnx, scope: Telescope, night_date: datetime.date,
                      user_id: Optional[int], explain: bool, rejected: List[_Rejected]):
    """Fetch projects for the telescope and split them into candidates and stage-1 rejects."""
    query = f"SELECT {_PROJECT_COLUMNS} FROM projects p"
    values = []

    if user_id is not None:
        query += " JOIN project_users pu ON pu.project_id = p.project_id AND pu.user_id = %s"
        values.append(user_id)

    query += " WHERE p.scope_id = %s"
    values.append(scope.scope_id)

    if not explain:
        # Cheap pre-filter, mirroring _project_exclusion_reason (see _collect_tasks).
        query += """ AND p.active = true
                     AND (p.start_date IS NULL OR p.start_date <= %s)
                     AND (p.end_date IS NULL OR p.end_date >= %s)
                     AND p.ra IS NOT NULL AND p.decl IS NOT NULL"""
        values.extend([night_date, night_date])
        if scope.min_dec is not None:
            query += " AND p.decl >= %s"
            values.append(scope.min_dec)
        if scope.max_dec is not None:
            query += " AND p.decl <= %s"
            values.append(scope.max_dec)

    query += " ORDER BY p.priority DESC, p.project_id DESC"

    projects = [_project_row_to_dict(row) for row in db.run_query(cnx, query, values) or []]
    if not projects:
        return []

    subframes = _fetch_subframes(cnx, [p["project_id"] for p in projects])
    users = _fetch_project_users(cnx, [p["project_id"] for p in projects])
    scope_filters = _scope_filter_ids(cnx, scope.scope_id)

    candidates = []
    for project in projects:
        project["user_ids"] = users.get(project["project_id"], [])
        reason = _project_exclusion_reason(project, scope, night_date)
        if reason is None:
            pending = [s for s in subframes.get(project["project_id"], []) if _subframe_pending(s)]
            on_scope = [s for s in pending if s["filter_id"] in scope_filters]
            reason = _subframe_exclusion_reason(pending, on_scope)
            # Only the work this telescope can still do is worth returning.
            project["subframes"] = on_scope

        if reason is not None:
            if explain:
                rejected.append(_Rejected(
                    kind="project", ident=project["project_id"], label=project["name"],
                    reason=reason))
            continue

        candidates.append(Candidate(
            kind="project",
            ident=project["project_id"],
            label=project["name"],
            ra_deg=observability.ra_hours_to_deg(project["ra"]),
            dec_deg=project["decl"],
            constraints=Constraints(
                min_alt=project["min_alt"], moon_distance=project["moon_distance"],
                max_moon_phase=project["max_moon_phase"], max_sun_alt=project["max_sun_alt"]),
            priority=project["priority"] or 0,
            payload={k: v for k, v in project.items() if not k.startswith("_")},
        ))
    return candidates


def _sort_key(candidate: Candidate):
    """priority desc, tasks before projects, newest id first."""
    return (-candidate.priority, 0 if candidate.kind == "task" else 1, -candidate.ident)


def compute_night_plan(cnx, scope_id: int, night_date: Optional[datetime.date] = None,
                       user_id: Optional[int] = None, explain: bool = False) -> dict:
    """
    Build the night plan for one telescope and one night.

    `night_date` labels the night per the NINA "date - 12h" rule
    (`hevelius.night.night_date`); it defaults to the night in progress at the
    telescope right now. `user_id` narrows the plan to one user's tasks and
    project memberships.

    `explain=True` adds an `excluded` list saying why each non-planned
    task/project was left out. Note that it deliberately drops the SQL
    pre-filter to do so, so it walks *every* task on the telescope - including
    long-finished ones - and the answer grows with the archive rather than with
    the plan. That's the price of being able to explain a task that was
    rejected for its state; narrow it with `user_id` on a large archive.
    """
    started = time_module.monotonic()
    scope = _fetch_telescope(cnx, scope_id)

    if night_date is None:
        night_date = night.night_date(
            datetime.datetime.now(datetime.timezone.utc), scope.timezone)

    location = scope.location()
    night_start, night_end = night.night_window(location, night_date, scope.timezone)
    moonrise, moonset = night.moon_rise_set(location, night_start, night_end)
    night_mid = night_start + (night_end - night_start) / 2.0

    rejected: List[_Rejected] = []
    candidates = _collect_tasks(cnx, scope, night_start, night_end, user_id, explain, rejected)
    candidates += _collect_projects(cnx, scope, night_date, user_id, explain, rejected)

    items = []
    for candidate in sorted(candidates, key=_sort_key):
        result = observability.check_visibility(
            candidate.ra_deg, candidate.dec_deg, candidate.constraints,
            location, night_start, night_end)
        if not result.visible:
            if explain:
                rejected.append(_Rejected(
                    kind=candidate.kind, ident=candidate.ident, label=candidate.label,
                    reason=result.reason))
            continue
        items.append({
            "kind": candidate.kind,
            candidate.kind: candidate.payload,
            "visibility": {
                "check_time_utc": _iso_utc(result.check_time),
                "altitude_deg": result.altitude_deg,
                "azimuth_deg": result.azimuth_deg,
                "moon_separation_deg": result.moon_separation_deg,
                "sun_altitude_deg": result.sun_altitude_deg,
            },
        })

    plan = {
        "scope_id": scope.scope_id,
        "scope_name": scope.name,
        "night_date": night_date,
        "timezone": scope.timezone,
        "night_start_utc": _iso_utc(night_start),
        "night_end_utc": _iso_utc(night_end),
        "moonrise_utc": _iso_utc(moonrise),
        "moonset_utc": _iso_utc(moonset),
        "moon_illumination_pct": round(night.moon_illumination_pct(night_mid), 2),
        "generated_at": _iso_utc(datetime.datetime.now(datetime.timezone.utc)),
        "items": items,
    }
    if explain:
        plan["excluded"] = [
            {
                "kind": r.kind,
                "task_id": r.ident if r.kind == "task" else None,
                "project_id": r.ident if r.kind == "project" else None,
                "name": r.label,
                "reason": r.reason,
            }
            for r in rejected
        ]

    logger.info(
        "night-plan: scope=%s (%s) night=%s user=%s items=%d excluded=%d in %.2fs",
        scope.scope_id, scope.name, night_date, user_id, len(items), len(rejected),
        time_module.monotonic() - started,
    )
    return plan
