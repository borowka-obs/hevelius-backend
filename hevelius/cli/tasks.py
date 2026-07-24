"""CLI commands for listing and inspecting tasks."""

import sys
from datetime import datetime

from hevelius import db
from hevelius.utils import format_dec, format_ra


def _ansi(code: str, text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _fmt_ts(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16]


def _resolve_state(conn, state_arg):
    """Accept numeric state id or state name; return int or raise ValueError."""
    if state_arg is None:
        return None
    text = str(state_arg).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    state_id = db.task_state_id_by_name(conn, text)
    if state_id is None:
        raise ValueError(f"unknown task state {text!r} (use id or name, e.g. DONE)")
    return state_id


def list_tasks(args) -> int:
    """
    CLI: paginated task listing with filters and sorting.

    Defaults: first 100 rows, sorted by task_id descending (latest first).
    """
    sort_by = getattr(args, "sort_by", None) or "task_id"
    sort_order = getattr(args, "sort_order", None) or "desc"
    if sort_by not in db.TASK_LIST_SORT_FIELDS:
        print(
            f"ERROR: invalid --sort-by {sort_by!r}. "
            f"Choose from: {', '.join(sorted(db.TASK_LIST_SORT_FIELDS))}",
            file=sys.stderr,
        )
        return 1
    if sort_order not in ("asc", "desc"):
        print("ERROR: --sort-order must be 'asc' or 'desc'.", file=sys.stderr)
        return 1

    limit = getattr(args, "limit", 100)
    if limit is None or limit < 1:
        print("ERROR: --limit must be a positive integer.", file=sys.stderr)
        return 1
    offset = getattr(args, "offset", 0) or 0
    if offset < 0:
        print("ERROR: --offset must be >= 0.", file=sys.stderr)
        return 1

    try:
        conn = db.connect()
    except Exception as exc:
        print(f"ERROR: could not connect to database: {exc}", file=sys.stderr)
        return 1

    try:
        try:
            state = _resolve_state(conn, getattr(args, "state", None))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        filters = dict(
            object_name=getattr(args, "object", None) or None,
            user_id=getattr(args, "user_id", None),
            user_login=getattr(args, "user", None) or None,
            scope_id=getattr(args, "scope_id", None),
            state=state,
            project_id=getattr(args, "project_id", None),
        )
        total = db.tasks_count(conn, **filters)
        rows = db.tasks_list(
            conn,
            **filters,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
    finally:
        conn.close()

    color = not getattr(args, "no_color", False) and sys.stdout.isatty()

    def dim(s):
        return _ansi("2", s, color)

    def bold(s):
        return _ansi("1", s, color)

    shown = len(rows or [])
    end = offset + shown
    print(
        bold("Tasks")
        + dim(f"  showing {offset + 1 if shown else 0}–{end} of {total:,}")
        + dim(f"  sort={sort_by} {sort_order}")
    )
    print(
        f"{'ID':>8}  {'State':<10}  {'Object':<16}  {'User':<12}  "
        f"{'Scope':>5}  {'Exp':>5}  {'Filt':<6}  {'Bin':>3}  "
        f"{'Created':<16}  RA/Dec"
    )
    print(dim("-" * 110))

    if not rows:
        print(dim("  (no matches)"))
        return 0

    for row in rows:
        (
            task_id, _state_id, state_name, obj, login, scope_id, _tel_name,
            exposure, filt, binning, created, _performed, ra, decl,
        ) = row
        st = (state_name or str(_state_id) or "—")[:10]
        obj_s = (obj or "—")[:16]
        user_s = (login or "—")[:12]
        scope_s = f"{scope_id}" if scope_id is not None else "—"
        exp_s = f"{exposure:g}" if exposure is not None else "—"
        filt_s = (filt or "—")[:6]
        bin_s = f"{binning}" if binning is not None else "—"
        created_s = _fmt_ts(created)
        if ra is not None and decl is not None:
            coords = f"{format_ra(float(ra))} {format_dec(float(decl))}"
        else:
            coords = "—"
        print(
            f"{task_id:>8}  {st:<10}  {obj_s:<16}  {user_s:<12}  "
            f"{scope_s:>5}  {exp_s:>5}  {filt_s:<6}  {bin_s:>3}  "
            f"{created_s:<16}  {coords}"
        )

    if end < total:
        print(dim(f"  … {total - end:,} more (use --offset {end} or raise --limit)"))
    return 0
