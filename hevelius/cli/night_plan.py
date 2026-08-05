"""CLI command showing the night plan for a telescope (OS-4, #46)."""

import datetime
import sys

from hevelius import db, night_plan
from hevelius.utils import format_dec, format_ra


def _ansi(code: str, text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _hhmm(iso_utc):
    """'2026-08-03T19:42:00Z' -> '19:42 UTC', for the night summary lines."""
    if not iso_utc:
        return "—"
    return f"{iso_utc[11:16]} UTC"


def night_plan_show(args) -> int:
    """
    CLI: print the observing plan for one telescope and one night.

    A thin wrapper over hevelius.night_plan - same computation the
    /api/night-plan endpoint runs, so this is the way to debug a "why isn't my
    target in the plan" question without going through the web UI (--explain).
    """
    date_arg = getattr(args, "date", None)
    night_date = None
    if date_arg:
        try:
            night_date = datetime.date.fromisoformat(str(date_arg))
        except ValueError:
            print(f"ERROR: invalid --date {date_arg!r}, expected YYYY-MM-DD.", file=sys.stderr)
            return 1

    try:
        conn = db.connect()
    except Exception as exc:
        print(f"ERROR: could not connect to database: {exc}", file=sys.stderr)
        return 1

    try:
        plan = night_plan.compute_night_plan(
            conn,
            scope_id=args.scope_id,
            night_date=night_date,
            user_id=getattr(args, "user_id", None),
            explain=getattr(args, "explain", False),
        )
    except night_plan.NightPlanError as err:
        print(f"ERROR: {err.message}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    color = not getattr(args, "no_color", False) and sys.stdout.isatty()

    def dim(text):
        return _ansi("2", text, color)

    def bold(text):
        return _ansi("1", text, color)

    print(bold(f"Night plan for {plan['scope_name']} (scope {plan['scope_id']}), "
               f"night of {plan['night_date']}")
          + dim(f"  [{plan['timezone']}]"))
    print(dim(f"  sunset {_hhmm(plan['night_start_utc'])} → sunrise {_hhmm(plan['night_end_utc'])}"
              f"   moonrise {_hhmm(plan['moonrise_utc'])}  moonset {_hhmm(plan['moonset_utc'])}"
              f"   moon {plan['moon_illumination_pct']:.0f}% illuminated"))
    print()

    print(f"{'Kind':<8}  {'ID':>6}  {'Name':<24}  {'Alt':>6}  {'Az':>6}  "
          f"{'Moon':>6}  {'Sun':>6}  {'At':<10}  RA/Dec")
    print(dim("-" * 110))

    if not plan["items"]:
        print(dim("  (nothing observable tonight)"))

    for item in plan["items"]:
        kind = item["kind"]
        entity = item[kind]
        vis = item["visibility"]
        ident = entity["task_id"] if kind == "task" else entity["project_id"]
        label = (entity["object"] if kind == "task" else entity["name"]) or "—"
        ra, decl = entity["ra"], entity["decl"]
        coords = f"{format_ra(float(ra))} {format_dec(float(decl))}" if ra is not None and decl is not None else "—"
        print(f"{kind:<8}  {ident:>6}  {label[:24]:<24}  {vis['altitude_deg']:>5.1f}°  "
              f"{vis['azimuth_deg']:>5.1f}°  {vis['moon_separation_deg']:>5.1f}°  "
              f"{vis['sun_altitude_deg']:>5.1f}°  {_hhmm(vis['check_time_utc']):<10}  {coords}")

    print()
    print(dim(f"  {len(plan['items'])} observable item(s)"))

    if "excluded" in plan:
        print()
        print(bold(f"Excluded ({len(plan['excluded'])})"))
        print(dim("-" * 110))
        for entry in plan["excluded"]:
            ident = entry["task_id"] if entry["kind"] == "task" else entry["project_id"]
            print(f"{entry['kind']:<8}  {ident:>6}  {(entry['name'] or '—')[:24]:<24}  {entry['reason']}")

    return 0
