"""POST /recommend — kick off a best-time recommendation (async).

Body: {"title": "...", "duration_min": 90, "within_days": 14}

Reads the cached academic/community events (populated by /sync), computes
conflict-free candidate slots deterministically, writes a PENDING recommendation
record, and hands the slow model ranking to an async worker Lambda so this
endpoint returns instantly — free-tier model latency can exceed API Gateway's
29s cap, so the model call must not run inline. The dashboard polls
GET /recommendations until the record flips to done.

Requires an API key: it spends model quota.
"""
import datetime
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

import model as reco_model
from common import EVENT_PK, RECO_PK, TABLE, local_now, resp

APP_TZ_NAME = os.environ.get("APP_TZ", "Africa/Lagos")
MAX_WITHIN_DAYS = int(os.environ.get("MAX_WITHIN_DAYS", "30"))
WORKER_NAME = os.environ.get("RECO_WORKER_NAME", "")

_lambda = boto3.client("lambda")


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
    slots = reco_model.shortlist(all_free)

    requested_at = local_now().isoformat()
    base = {
        "PK": RECO_PK, "SK": requested_at, "title": title,
        "duration_min": duration_min, "within_days": within_days,
        "candidate_count": len(slots), "total_free": len(all_free),
    }

    # No free slot: resolve immediately, honestly, no worker needed.
    if not slots:
        rec = reco_model.recommend(title, duration_min, [], academic, community, APP_TZ_NAME)
        TABLE.put_item(Item={**base, "status": "done", "source": rec["source"],
                             "reasoning": rec["reasoning"], "ranked": rec["ranked"]})
        return resp(200, {"ok": True, "status": "done", "requested_at": requested_at,
                          "title": title, **rec, "candidate_count": 0, "total_free": 0})

    # Write pending, then hand the slow model call to the worker.
    TABLE.put_item(Item={**base, "status": "pending", "source": "pending",
                         "reasoning": "", "ranked": []})
    _lambda.invoke(
        FunctionName=WORKER_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "requested_at": requested_at, "title": title, "duration_min": duration_min,
            "slots": slots, "academic": academic, "community": community,
            "timezone": APP_TZ_NAME,
        }).encode(),
    )

    print("[recommend] queued " + json.dumps({
        "requested_at": requested_at, "title": title,
        "shortlisted": len(slots), "total_free": len(all_free)}))
    return resp(202, {
        "ok": True, "status": "pending", "requested_at": requested_at,
        "title": title, "duration_min": duration_min, "within_days": within_days,
        "candidate_count": len(slots), "total_free": len(all_free),
        "poll": "GET /recommendations",
    })
