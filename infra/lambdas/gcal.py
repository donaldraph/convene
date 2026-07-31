"""Google Calendar client. Stdlib only (urllib), same shape standup-brief proved:
exchange the stored refresh token for a short-lived access token at call time,
never store access tokens.

Convene reads TWO calendars (academic + community), found by NAME in the
account's calendar list so nothing hardcodes a calendar id. Events are fetched
over a forward-looking window, recurring events expanded.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"


def access_token(oauth):
    """Exchange the stored refresh token for a short-lived access token."""
    data = urllib.parse.urlencode(
        {
            "client_id": oauth["client_id"],
            "client_secret": oauth["client_secret"],
            "refresh_token": oauth["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())["access_token"]


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def find_calendars(token, names):
    """Map calendar display names -> calendar ids, case-insensitive.

    Returns (found: {name: {id, timeZone}}, missing: [name]). Missing names are
    the caller's problem to surface honestly; nothing is guessed.
    """
    items = _get(CAL_LIST_URL, token).get("items", [])
    by_name = {c.get("summary", "").strip().lower(): c for c in items}
    # The literal "primary" always resolves to the account's main calendar,
    # whatever its display name (Google names it after the email). Lets a user
    # use their existing primary as one source without renaming anything.
    primary = next((c for c in items if c.get("primary")), None)
    found, missing = {}, []
    for name in names:
        if name.strip().lower() == "primary" and primary:
            found[name] = {"id": "primary", "timeZone": primary.get("timeZone", "UTC")}
            continue
        cal = by_name.get(name.strip().lower())
        if cal:
            found[name] = {"id": cal["id"], "timeZone": cal.get("timeZone", "UTC")}
        else:
            missing.append(name)
    return found, missing


def parse_event(ev):
    """Flatten one Google event to the fields conflict detection needs.

    Timed events carry start.dateTime (RFC3339 with offset); all-day events
    carry start.date (YYYY-MM-DD, end date exclusive per Google).
    """
    start = ev.get("start", {})
    end = ev.get("end", {})
    return {
        "id": ev["id"],
        "summary": ev.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "location": ev.get("location"),
        "url": ev.get("htmlLink"),
    }


def fetch_window(token, calendar_id, start_utc, end_utc):
    """All events in [start_utc, end_utc), recurring expanded, start order."""
    cal = urllib.parse.quote(calendar_id)
    events, page_token = [], None
    while True:
        params = {
            "timeMin": start_utc.isoformat(),
            "timeMax": end_utc.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _get(EVENTS_URL.format(cal=cal) + "?" + urllib.parse.urlencode(params), token)
        events += [parse_event(e) for e in payload.get("items", [])
                   if e.get("status") != "cancelled"]
        page_token = payload.get("nextPageToken")
        if not page_token:
            return events


def window(days, now=None):
    """The sync window: from the start of today (UTC) forward `days` days.

    Starting at today 00:00 rather than `now` keeps events from earlier today
    visible, which matters when a conflict involves something already running.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + datetime.timedelta(days=days)
