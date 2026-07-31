"""GET /conflicts - the dashboard read: conflicts + last-sync freshness.

?status=open (default) | all. Public read like study-conscience's brief: the
data is my own two calendars' collisions, not secrets, and the write path is
key-gated.
"""
from boto3.dynamodb.conditions import Key

from common import CONFLICT_PK, SYNC_PK, TABLE, resp


def handler(event, context):
    want = ((event.get("queryStringParameters") or {}).get("status") or "open").lower()

    items = TABLE.query(KeyConditionExpression=Key("PK").eq(CONFLICT_PK)).get("Items", [])
    if want != "all":
        items = [i for i in items if i.get("status") == want]
    for i in items:
        i.pop("PK", None)
        i["id"] = i.pop("SK")

    syncs = TABLE.query(KeyConditionExpression=Key("PK").eq(SYNC_PK)).get("Items", [])
    last_sync = {s["SK"]: {"calendar": s.get("calendar"), "at": s.get("at"),
                           "events": s.get("events")} for s in syncs}

    items.sort(key=lambda i: (i.get("academic", {}).get("start") or "", i["id"]))
    return resp(200, {"conflicts": items, "count": len(items), "last_sync": last_sync})
