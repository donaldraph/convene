"""Deterministic conflict detection between the academic and community calendars.

Pure functions, no AWS, no network: unit-testable on any box. This is plain
interval math on purpose - the AI's job in convene is recommending better
slots, not deciding whether two meetings overlap.

Two conflict types:
  hard     - two TIMED events whose intervals overlap (startA < endB and
             startB < endA). The unambiguous collision.
  same_day - an ALL-DAY event on one calendar sharing a date with an event on
             the other. Flagged separately because an all-day "Exam week" vs a
             2h workshop is a judgment call, not a certain collision; the UI
             presents these as warnings, never as hard conflicts.

Conflict ids are a hash of the two event ids, so re-detection over the same
pair yields the same id and status survives re-syncs (same exactly-once shape
study-conscience and recon proved).
"""
import datetime
import hashlib


def _parse_dt(value):
    """RFC3339 timed value -> aware datetime. Google emits offsets, not 'Z'-only."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dates_of(ev):
    """The set of dates an all-day event covers. Google end.date is exclusive."""
    start = datetime.date.fromisoformat(ev["start"])
    end = datetime.date.fromisoformat(ev["end"])
    days = max((end - start).days, 1)
    return {start + datetime.timedelta(days=i) for i in range(days)}


def _timed_dates(ev):
    """Dates a timed event touches, in its own offset (usually one)."""
    start, end = _parse_dt(ev["start"]), _parse_dt(ev["end"])
    out, day = set(), start.date()
    while day <= end.date():
        out.add(day)
        day += datetime.timedelta(days=1)
    return out


def conflict_id(event_a, event_b):
    pair = "|".join(sorted([event_a["id"], event_b["id"]]))
    return hashlib.sha256(pair.encode()).hexdigest()[:16]


def _pair(kind, academic, community):
    return {
        "id": conflict_id(academic, community),
        "type": kind,
        "academic": {k: academic[k] for k in ("id", "summary", "start", "end", "all_day")},
        "community": {k: community[k] for k in ("id", "summary", "start", "end", "all_day")},
    }


def detect(academic_events, community_events):
    """All conflicts between the two calendars, deterministic order (by id).

    Input events are gcal.parse_event dicts. Output: list of conflict dicts
    with stable ids, type hard | same_day, and both events embedded for
    display. No network, no clock: pure function of its inputs.
    """
    out = []
    for a in academic_events:
        for c in community_events:
            if not a["all_day"] and not c["all_day"]:
                if _parse_dt(a["start"]) < _parse_dt(c["end"]) and \
                   _parse_dt(c["start"]) < _parse_dt(a["end"]):
                    out.append(_pair("hard", a, c))
            else:
                a_days = _dates_of(a) if a["all_day"] else _timed_dates(a)
                c_days = _dates_of(c) if c["all_day"] else _timed_dates(c)
                if a_days & c_days:
                    out.append(_pair("same_day", a, c))
    return sorted(out, key=lambda x: x["id"])
