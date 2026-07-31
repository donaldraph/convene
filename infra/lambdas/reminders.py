"""EventBridge-triggered reminder send. Pulls the current open/doing tasks and
the near-term conflicts, formats a digest, and sends it to Telegram.

Telegram creds come from Secrets Manager (convene/telegram). If the secret is
missing the send falls back to logging so the scheduled run never crashes -
same honest degradation as study-conscience. Nothing here fabricates data: an
empty board and no conflicts produce a short "all clear" note, not fake items.
"""
import datetime
import json
import os
import urllib.error
import urllib.request

from boto3.dynamodb.conditions import Key

from common import CONFLICT_PK, TASK_PK, TABLE, get_secret, local_now

TELEGRAM_SECRET_NAME = os.environ.get("TELEGRAM_SECRET_NAME", "convene/telegram")
REMIND_WITHIN_DAYS = int(os.environ.get("REMIND_WITHIN_DAYS", "7"))


def _active_tasks():
    items = TABLE.query(KeyConditionExpression=Key("PK").eq(TASK_PK)).get("Items", [])
    active = [i for i in items if i.get("status") in ("open", "doing")]
    active.sort(key=lambda i: (i.get("due") or "9999-99-99", i.get("created_at", "")))
    return active


def _upcoming_conflicts():
    items = TABLE.query(KeyConditionExpression=Key("PK").eq(CONFLICT_PK)).get("Items", [])
    horizon = (datetime.datetime.now(datetime.timezone.utc)
               + datetime.timedelta(days=REMIND_WITHIN_DAYS)).isoformat()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    open_soon = [i for i in items if i.get("status") == "open"
                 and (i.get("academic", {}).get("start") or "") <= horizon
                 and (i.get("academic", {}).get("start") or "") >= now[:10]]
    open_soon.sort(key=lambda i: i.get("academic", {}).get("start") or "")
    return open_soon


def format_digest(tasks, conflicts):
    h = local_now().hour
    greet = "Good morning." if h < 12 else "Good afternoon." if h < 17 else "Good evening."
    lines = [greet, f"Convene digest for {local_now().date().isoformat()}", ""]

    if conflicts:
        lines.append(f"Calendar conflicts in the next {REMIND_WITHIN_DAYS} days:")
        for c in conflicts[:5]:
            a = c.get("academic", {})
            b = c.get("community", {})
            lines.append(f"  - {a.get('summary', '?')} vs {b.get('summary', '?')} "
                         f"({a.get('start', '?')[:16].replace('T', ' ')})")
        lines.append("")
    else:
        lines.append("No calendar conflicts in the window. Clear.")
        lines.append("")

    if tasks:
        lines.append("Open team tasks:")
        for t in tasks[:10]:
            due = f", due {t['due']}" if t.get("due") else ""
            lines.append(f"  - [{t.get('status')}] {t.get('title')} -> {t.get('assignee')}{due}")
    else:
        lines.append("No open team tasks.")
    return "\n".join(lines)


def _telegram_creds():
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        return os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    try:
        s = get_secret(TELEGRAM_SECRET_NAME)
        return s.get("bot_token"), s.get("chat_id")
    except Exception:  # noqa: BLE001 - no secret -> log-only fallback
        return None, None


def send_telegram(text):
    token, chat_id = _telegram_creds()
    if not token or not chat_id:
        print("[STUB telegram] no creds, would send:\n" + text)
        return {"sent": False, "stub": True}
    body = json.dumps({"chat_id": chat_id, "text": text[:4096]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.load(r).get("ok", False)
        print(f"[telegram] sent ok={ok}")
        return {"sent": bool(ok)}
    except urllib.error.HTTPError as exc:
        print(f"[telegram] failed HTTP {exc.code}: {exc.read().decode()[:200]}")
        return {"sent": False, "error": f"http {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] failed: {type(exc).__name__}")
        return {"sent": False, "error": type(exc).__name__}


def handler(event, context):
    tasks = _active_tasks()
    conflicts = _upcoming_conflicts()
    text = format_digest(tasks, conflicts)
    result = send_telegram(text)
    print("[reminders] " + json.dumps({"tasks": len(tasks), "conflicts": len(conflicts),
                                       "sent": result.get("sent")}))
    return {"ok": True, "tasks": len(tasks), "conflicts": len(conflicts), "delivery": result}
