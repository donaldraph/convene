"""Split ONE calendar's events into academic vs community by a title tag.

For the common student setup: a single Google Calendar where event type is
signalled in the title ("Academic: Algorithms lecture", "Outreach: AWS
session"). Pure function, no AWS, unit-testable.

The rule is deliberately simple and legible so a user can predict it: an event
is academic if its title contains the academic tag (case-insensitive),
otherwise it is community. One knob, no hidden heuristics.
"""


def split_by_tag(events, academic_tag="academic"):
    """Return (academic_events, community_events) preserving input order."""
    tag = academic_tag.strip().lower()
    academic, community = [], []
    for ev in events:
        if tag in ev.get("summary", "").lower():
            academic.append(ev)
        else:
            community.append(ev)
    return academic, community
