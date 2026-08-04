"""
Tests hevelius.night.night_date() - the NINA "date - 12h" night identity rule.
"""

import datetime

import pytest

from hevelius.night import night_date

WARSAW = "Europe/Warsaw"
UTC = datetime.timezone.utc


# Worked examples from the issue: site in Europe/Warsaw (UTC+2, CEST, in
# August), evening / late-night / next-afternoon cases.
@pytest.mark.parametrize("utc_time, expected_date", [
    # Local 2026-08-03 22:00 CEST -> UTC 2026-08-03 20:00
    (datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 3)),
    # Local 2026-08-04 03:00 CEST -> UTC 2026-08-04 01:00
    (datetime.datetime(2026, 8, 4, 1, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 3)),
    # Local 2026-08-04 13:00 CEST -> UTC 2026-08-04 11:00
    (datetime.datetime(2026, 8, 4, 11, 0, 0, tzinfo=UTC), datetime.date(2026, 8, 4)),
])
def test_night_date_worked_examples(utc_time, expected_date):
    assert night_date(utc_time, WARSAW) == expected_date


def test_night_date_boundary_at_local_noon():
    """Local 12:00:00 minus 12h lands exactly on local midnight: same day."""
    utc_time = datetime.datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)  # local 12:00:00 CEST
    assert night_date(utc_time, WARSAW) == datetime.date(2026, 8, 4)


def test_night_date_boundary_just_before_local_noon():
    """One second earlier, it rolls back onto the previous night."""
    utc_time = datetime.datetime(2026, 8, 4, 9, 59, 59, tzinfo=UTC)  # local 11:59:59 CEST
    assert night_date(utc_time, WARSAW) == datetime.date(2026, 8, 3)


def test_night_date_naive_datetime_assumed_utc():
    """A naive datetime is treated as if it were already UTC."""
    aware = datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC)
    naive = datetime.datetime(2026, 8, 3, 20, 0, 0)
    assert night_date(naive, WARSAW) == night_date(aware, WARSAW)


def test_night_date_aware_datetime_in_other_timezone_is_converted():
    """The same instant, expressed in a different zone, gives the same result."""
    utc_time = datetime.datetime(2026, 8, 4, 1, 0, 0, tzinfo=UTC)
    eastern_time = utc_time.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
    assert night_date(eastern_time, WARSAW) == night_date(utc_time, WARSAW)


def test_night_date_utc_site():
    """A telescope with tz_name='UTC' just applies the -12h rule directly."""
    utc_time = datetime.datetime(2026, 8, 3, 20, 0, 0, tzinfo=UTC)
    assert night_date(utc_time, "UTC") == datetime.date(2026, 8, 3)
