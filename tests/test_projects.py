"""
Tests the project completion arithmetic (OS-6, #114).

No DB and no HTTP: hevelius.projects is pure arithmetic over subframe dicts.
The API-level checks that these numbers actually reach the responses live in
tests/test_api.py and tests/test_api_night_plan.py.
"""

import pytest

from hevelius.projects import completion, subframe_pending, subframe_remaining


def sub(count=0, goal_count=10, active=True):
    """A subframe dict shaped like the ones the API and the night plan build."""
    return {"count": count, "goal_count": goal_count, "active": active}


@pytest.mark.parametrize('subframe, pending', [
    (sub(count=0, goal_count=10), True),
    (sub(count=9, goal_count=10), True),
    (sub(count=10, goal_count=10), False),
    (sub(count=12, goal_count=10), False),          # overshot: still nothing left
    (sub(count=0, goal_count=0), False),            # goal of zero is met on arrival
    (sub(count=None, goal_count=10), True),         # no frames captured yet
    (sub(count=0, goal_count=None), True),          # open-ended: no goal set
    (sub(count=99, goal_count=None), True),         # open-ended stays open
    (sub(count=0, goal_count=10, active=False), False),   # switched off
    (sub(count=0, goal_count=None, active=False), False),
])
def test_subframe_pending(subframe, pending):
    """A subframe is pending unless it is inactive or has met its goal."""
    assert subframe_pending(subframe) is pending


@pytest.mark.parametrize('subframe, remaining', [
    (sub(count=0, goal_count=10), 10),
    (sub(count=3, goal_count=10), 7),
    (sub(count=10, goal_count=10), 0),
    (sub(count=12, goal_count=10), 0),              # overshoot never goes negative
    (sub(count=None, goal_count=10), 10),
    (sub(count=0, goal_count=None), 0),             # pending, but no number to report
    (sub(count=0, goal_count=10, active=False), 0),
])
def test_subframe_remaining(subframe, remaining):
    """Remaining counts the frames still owed, clamped at zero."""
    assert subframe_remaining(subframe) == remaining


def test_completion_sums_over_subframes():
    """The project total is the sum of what its subframes still owe."""
    assert completion([sub(count=3, goal_count=10), sub(count=1, goal_count=5)]) == {
        "subframes_remaining": 11, "is_complete": False}


def test_completion_ignores_inactive_and_finished_subframes():
    """Only active, unfinished subframes contribute - and keep the project incomplete."""
    assert completion([
        sub(count=10, goal_count=10),
        sub(count=0, goal_count=20, active=False),
    ]) == {"subframes_remaining": 0, "is_complete": True}


def test_completion_of_open_ended_subframe_is_incomplete_but_uncounted():
    """No goal_count means work with no number on it: incomplete, remaining 0."""
    assert completion([sub(count=42, goal_count=None)]) == {
        "subframes_remaining": 0, "is_complete": False}


@pytest.mark.parametrize('subframes', [[], None])
def test_completion_without_subframes_is_complete(subframes):
    """A project with nothing to shoot is complete - the night plan's own test."""
    assert completion(subframes) == {"subframes_remaining": 0, "is_complete": True}
