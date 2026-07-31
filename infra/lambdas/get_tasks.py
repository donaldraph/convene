"""GET /tasks - the team task board. Public read. ?status=open|doing|done|all."""
from boto3.dynamodb.conditions import Key

from common import TASK_PK, TABLE, resp

_ORDER = {"open": 0, "doing": 1, "done": 2}


def handler(event, context):
    want = ((event.get("queryStringParameters") or {}).get("status") or "all").lower()
    items = TABLE.query(KeyConditionExpression=Key("PK").eq(TASK_PK)).get("Items", [])
    for i in items:
        i.pop("PK", None)
        i["id"] = i.pop("SK")
    if want != "all":
        items = [i for i in items if i.get("status") == want]
    # Active tasks first, then earliest due date, then oldest created.
    items.sort(key=lambda i: (_ORDER.get(i.get("status"), 9),
                              i.get("due") or "9999-99-99", i.get("created_at", "")))
    return resp(200, {"tasks": items, "count": len(items)})
