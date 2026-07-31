"""POST /sync — pull the calendar(s), reconcile the cache, detect conflicts.

The one write-path for calendar state. Two source modes:

  two-calendar (default): resolve an academic calendar and a community calendar
    BY NAME and read each.
  split (SPLIT_CALENDAR set): read ONE calendar and classify each event as
    academic vs community by a title tag (classify.split_by_tag). This fits a
    student who keeps a single Google Calendar and labels event type in the
    title.

Either way the tail is identical:
  - reconcile the EVENT#<source> partitions: upsert what exists now, DELETE
    cached events that vanished or moved (a moved event changes its SK, and a
    stale SK would keep a phantom conflict alive)
  - run the deterministic conflict engine over the fresh academic/community sets
  - upsert conflicts by stable id: new ones open, still-present ones keep their
    status, gone ones get status=cleared (kept for history)

If a named calendar is missing the response says so honestly and nothing is
half-synced: better a loud 424 than a silent half-empty cache.
"""
import json
import os

from boto3.dynamodb.conditions import Key

import classify
import conflicts as conflict_engine
import gcal
from common import (
    CONFLICT_PK,
    EVENT_PK,
    SYNC_PK,
    TABLE,
    get_secret,
    local_now,
    resp,
)

OAUTH_SECRET_NAME = os.environ.get("GOOGLE_OAUTH_SECRET_NAME", "convene/google-oauth")
ACADEMIC_CAL = os.environ.get("ACADEMIC_CAL_NAME", "Academic")
COMMUNITY_CAL = os.environ.get("COMMUNITY_CAL_NAME", "Community")
# Split mode: when set, read this one calendar and tag-classify its events.
SPLIT_CALENDAR = os.environ.get("SPLIT_CALENDAR", "").strip()
ACADEMIC_TAG = os.environ.get("ACADEMIC_TAG", "academic")
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "30"))

SOURCES = {"academic": ACADEMIC_CAL, "community": COMMUNITY_CAL}


def _event_sk(ev):
    return f"{ev['start']}#{ev['id']}"


def _reconcile_events(source, events):
    """Make the EVENT#<source> partition equal exactly `events`. Returns counts."""
    pk = EVENT_PK.format(source=source)
    existing = {}
    q = TABLE.query(KeyConditionExpression=Key("PK").eq(pk))
    for item in q.get("Items", []):
        existing[item["SK"]] = True
    fresh = {_event_sk(ev): ev for ev in events}

    with TABLE.batch_writer() as batch:
        for sk, ev in fresh.items():
            batch.put_item(Item={"PK": pk, "SK": sk, **ev})
        for sk in existing:
            if sk not in fresh:
                batch.delete_item(Key={"PK": pk, "SK": sk})
    return {"cached": len(fresh), "removed": len([s for s in existing if s not in fresh])}


def _reconcile_conflicts(found):
    """Upsert detected conflicts by stable id; clear the ones that vanished."""
    now = local_now().isoformat()
    existing = {i["SK"]: i for i in
                TABLE.query(KeyConditionExpression=Key("PK").eq(CONFLICT_PK)).get("Items", [])}
    fresh_ids = {c["id"] for c in found}

    opened = kept = cleared = 0
    with TABLE.batch_writer() as batch:
        for c in found:
            prev = existing.get(c["id"])
            if prev and prev.get("status") != "cleared":
                status, detected_at, kept = prev["status"], prev.get("detected_at", now), kept + 1
            else:
                status, detected_at, opened = "open", now, opened + 1
            batch.put_item(Item={
                "PK": CONFLICT_PK, "SK": c["id"], "status": status,
                "detected_at": detected_at, "type": c["type"],
                "academic": c["academic"], "community": c["community"],
            })
        for sk, item in existing.items():
            if sk not in fresh_ids and item.get("status") != "cleared":
                batch.put_item(Item={**item, "status": "cleared", "cleared_at": now})
                cleared += 1
    return {"open_new": opened, "still_open": kept, "cleared": cleared}


def _load_events(token, start, end):
    """Fetch and label events per mode. Returns (per_source, labels, missing).

    per_source: {"academic": [...], "community": [...]}
    labels:     {"academic": <display name>, "community": <display name>}
    missing:    list of calendar names not found (caller returns 424), or []
    """
    if SPLIT_CALENDAR:
        found, missing = gcal.find_calendars(token, [SPLIT_CALENDAR])
        if missing:
            return None, None, missing
        events = gcal.fetch_window(token, found[SPLIT_CALENDAR]["id"], start, end)
        academic, community = classify.split_by_tag(events, ACADEMIC_TAG)
        labels = {
            "academic": f"{SPLIT_CALENDAR} (title contains '{ACADEMIC_TAG}')",
            "community": f"{SPLIT_CALENDAR} (other events)",
        }
        return {"academic": academic, "community": community}, labels, []

    found, missing = gcal.find_calendars(token, list(SOURCES.values()))
    if missing:
        return None, None, missing
    per_source = {
        source: gcal.fetch_window(token, found[name]["id"], start, end)
        for source, name in SOURCES.items()
    }
    return per_source, dict(SOURCES), []


def run_sync():
    oauth = get_secret(OAUTH_SECRET_NAME)
    token = gcal.access_token(oauth)

    start, end = gcal.window(SYNC_DAYS)
    per_source, labels, missing = _load_events(token, start, end)
    if missing:
        return None, missing

    result = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "mode": "split" if SPLIT_CALENDAR else "two-calendar",
    }
    for source in ("academic", "community"):
        result[source] = {"calendar": labels[source],
                          **_reconcile_events(source, per_source[source])}

    detected = conflict_engine.detect(per_source["academic"], per_source["community"])
    result["conflicts"] = _reconcile_conflicts(detected)

    now = local_now().isoformat()
    for source in ("academic", "community"):
        TABLE.put_item(Item={
            "PK": SYNC_PK, "SK": source, "calendar": labels[source], "at": now,
            "events": result[source]["cached"],
        })
    return result, None


def handler(event, context):
    try:
        result, missing = run_sync()
    except Exception as exc:  # noqa: BLE001 — surface the real failure class
        print(f"[sync] failed: {type(exc).__name__}: {exc}")
        return resp(502, {"ok": False, "error": type(exc).__name__})
    if missing:
        return resp(424, {
            "ok": False,
            "error": f"calendar(s) not found by name: {', '.join(missing)}",
            "hint": "create/rename them in Google Calendar, or set SPLIT_CALENDAR "
                    "to read one calendar and tag events by title",
        })
    print("[sync] " + json.dumps(result))
    return resp(200, {"ok": True, **result})
