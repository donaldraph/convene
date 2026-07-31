"""POST /recommend — recommend the best time for a NEW event.

Body: {"title": "...", "duration_min": 90, "within_days": 14}

Reads the cached academic/community events (populated by /sync), computes
conflict-free candidate slots deterministically, then asks the model to rank
them with judgment. Stores the recommendation under RECO for the dashboard and
returns it. Requires an API key: it spends model quota.
"""
import datetime
import json
import os

from boto3.dynamodb.conditions import Key

import model as reco_model
from common import EVENT_PK, RECO_PK, TABLE, local_now, resp

APP_TZ_NAME = os.environ.get("APP_TZ", "Africa/Lagos")
MAX_WITHIN_DAYS = int(os.environ.get("MAX_WITHIN_DAYS", "30"))


def _cached_events(source):
    pk = EVENT_PK.format(source=source)
    items = TABLE.query(KeyConditionExpression=Key("PK").eq(pk)).get("Items", [])
    return [{k: i.get(k) for k in ("id", "summary", "start", "end", "all_day")} for i in items]


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"ok": False, "error": "body must be JSON"})

    title = (body.get("title") or "New event").strip()
    try:
        duration_min = int(body.get("duration_min", 60))
        within_days = min(int(body.get("within_days", 14)), MAX_WITHIN_DAYS)
    except (TypeError, ValueError):
        return resp(400, {"ok": False, "error": "duration_min and within_days must be integers"})
    if duration_min <= 0 or within_days <= 0:
        return resp(400, {"ok": False, "error": "duration_min and within_days must be positive"})

    academic = _cached_events("academic")
    community = _cached_events("community")

    now = datetime.datetime.now(datetime.timezone.utc)
    window_end = now + datetime.timedelta(days=within_days)
    all_free = reco_model.free_slots(duration_min, academic, community, now, window_end)
    # Rank a spread the model can handle fast, not all N half-hourly slots.
    slots = reco_model.shortlist(all_free)

    try:
        rec = reco_model.recommend(
            title, duration_min, slots, academic, community, APP_TZ_NAME)
    except Exception as exc:  # noqa: BLE001 — never 500 on the model path
        print(f"[recommend] model error: {type(exc).__name__}: {exc}")
        return resp(502, {"ok": False, "error": type(exc).__name__})

    requested_at = local_now().isoformat()
    TABLE.put_item(Item={
        "PK": RECO_PK, "SK": requested_at,
        "title": title, "duration_min": duration_min, "within_days": within_days,
        "source": rec["source"], "reasoning": rec["reasoning"],
        "ranked": rec["ranked"], "candidate_count": len(slots),
        "total_free": len(all_free),
    })

    print("[recommend] " + json.dumps({
        "title": title, "shortlisted": len(slots), "total_free": len(all_free),
        "source": rec["source"]}))
    return resp(200, {
        "ok": True, "requested_at": requested_at, "title": title,
        "duration_min": duration_min, "within_days": within_days,
        "candidate_count": len(slots), "total_free": len(all_free), **rec,
    })
