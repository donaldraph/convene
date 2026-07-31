"""GET /recommendations - the most recent best-time recommendations for the
dashboard. Public read. ?limit=N (default 5, newest first)."""
from boto3.dynamodb.conditions import Key

from common import RECO_PK, TABLE, resp


def handler(event, context):
    try:
        limit = min(int((event.get("queryStringParameters") or {}).get("limit", 5)), 25)
    except (TypeError, ValueError):
        limit = 5

    items = TABLE.query(
        KeyConditionExpression=Key("PK").eq(RECO_PK),
        ScanIndexForward=False,  # newest first
        Limit=limit,
    ).get("Items", [])
    for i in items:
        i.pop("PK", None)
        i["requested_at"] = i.pop("SK")
    return resp(200, {"recommendations": items, "count": len(items)})
