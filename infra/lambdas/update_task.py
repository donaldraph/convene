"""PATCH /tasks/{id} - update a task's status/assignee/due. Key-gated."""
import json

import botocore.exceptions

from common import TASK_PK, TABLE, local_now, resp

VALID_STATUS = {"open", "doing", "done"}


def handler(event, context):
    tid = (event.get("pathParameters") or {}).get("id")
    if not tid:
        return resp(400, {"ok": False, "error": "task id required in path"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"ok": False, "error": "body must be JSON"})

    updates = {}
    if "status" in body:
        st = (body["status"] or "").strip().lower()
        if st not in VALID_STATUS:
            return resp(400, {"ok": False, "error": f"status must be one of {sorted(VALID_STATUS)}"})
        updates["status"] = st
    if "assignee" in body:
        updates["assignee"] = (body["assignee"] or "").strip() or "unassigned"
    if "due" in body:
        updates["due"] = (body["due"] or "").strip()
    if not updates:
        return resp(400, {"ok": False, "error": "nothing to update (status/assignee/due)"})

    updates["updated_at"] = local_now().isoformat()
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
    names = {f"#{k}": k for k in updates}
    vals = {f":{k}": v for k, v in updates.items()}

    try:
        out = TABLE.update_item(
            Key={"PK": TASK_PK, "SK": tid},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
            ConditionExpression="attribute_exists(SK)",
            ReturnValues="ALL_NEW",
        )
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return resp(404, {"ok": False, "error": f"task {tid} not found"})
        raise

    task = out["Attributes"]
    task.pop("PK", None)
    task["id"] = task.pop("SK")
    return resp(200, {"ok": True, "task": task})
