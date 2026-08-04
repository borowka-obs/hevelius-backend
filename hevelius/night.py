"""
Night identity: which observing night a UTC instant belongs to.

Implements the NINA "date - 12h" rule: convert the instant to the
telescope's local civil time, subtract 12 hours, take the date. A night
session that spans local midnight (e.g. starts at 22:00, ends at 03:00
local) therefore collapses onto a single calendar date - the evening's
date.

Shared by Night Plan (OS-4), `observation_events.night_date` (OS-8), and
nightly Statistics grouping (OS-9) so all three consumers bucket
observations into nights the same way. Pure function, no DB dependency:
callers pass the telescope's IANA timezone name (`telescopes.timezone`,
see OS-2) rather than a scope/telescope object.
"""

import datetime
from zoneinfo import ZoneInfo


def night_date(t: datetime.datetime, tz_name: str) -> datetime.date:
    """
    Returns the observing night (a date) that the UTC instant `t` belongs
    to at the site identified by the IANA timezone `tz_name`
    (e.g. "Europe/Warsaw").

    `t` may be a naive datetime (assumed to already be UTC) or a
    timezone-aware datetime in any zone (converted to UTC first).
    """
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)

    local = t.astimezone(ZoneInfo(tz_name))
    return (local - datetime.timedelta(hours=12)).date()
