"""
Project completion arithmetic (OS-6, #114).

"How much of this project is still left to shoot" is asked in two places: the
projects API, which reports it to the Observation Planning UI, and the night
plan, which drops projects with nothing left to do. Both ask here, so the two
can never disagree about what "complete" means.

The rules are the ones the night plan has always used:

- an inactive subframe never counts - it is work the user switched off;
- a NULL `goal_count` means "no target set", which is open-ended rather than
  complete: a subframe nobody has given a goal to is still something the
  telescope can work on.
"""


def subframe_pending(subframe) -> bool:
    """Is there anything left to shoot for this subframe?"""
    if not subframe.get("active"):
        return False
    goal = subframe.get("goal_count")
    if goal is None:
        return True
    return (subframe.get("count") or 0) < goal


def subframe_remaining(subframe) -> int:
    """
    Frames still to capture for this subframe, 0 when there is nothing left.

    An open-ended subframe (no `goal_count`) contributes 0 even though it is
    pending: there is work to do, but no number to put on it. That is why the
    count is meant to be read together with `is_complete`, not instead of it.
    """
    goal = subframe.get("goal_count")
    if goal is None or not subframe.get("active"):
        return 0
    return max(0, goal - (subframe.get("count") or 0))


def completion(subframes) -> dict:
    """
    The computed fields the API adds to every project it returns.

    `is_complete` is the night plan's `already_complete` test: nothing is
    pending, so the telescope has no reason to point here. A project with no
    subframes at all is complete by that measure - there is nothing to shoot.
    """
    subframes = subframes or []
    return {
        "subframes_remaining": sum(subframe_remaining(s) for s in subframes),
        "is_complete": not any(subframe_pending(s) for s in subframes),
    }
