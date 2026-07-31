"""POST /tasks - create a team task. Key-gated (it writes to the team board)."""
import json
import uuid

from common import TASK_PK, TABLE, local_now, resp

VALID_STATUS = {"open", "doing", "done"}


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"ok": False, "error": "body must be JSON"})

    title = (body.get("title") or "").strip()
    if not title:
        return resp(400, {"ok": False, "error": "title is required"})

    assignee = (body.get("assignee") or "").strip() or "unassigned"
    due = (body.get("due") or "").strip()  # optional YYYY-MM-DD
    status = (body.get("status") or "open").strip().lower()
    if status not in VALID_STATUS:
        return resp(400, {"ok": False, "error": f"status must be one of {sorted(VALID_STATUS)}"})

    now = local_now().isoformat()
    tid = uuid.uuid4().hex[:12]
    item = {
        "PK": TASK_PK, "SK": tid, "title": title, "assignee": assignee,
        "due": due, "status": status, "created_at": now, "updated_at": now,
    }
    TABLE.put_item(Item=item)
    return resp(201, {"ok": True, "task": {**{k: v for k, v in item.items() if k != "PK"}, "id": tid}})
