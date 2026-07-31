"""Async worker for /recommend. Invoked (InvocationType=Event) by the API
handler with the shortlisted free slots and both calendars in the payload. Does
the Gemini ranking with the FULL Lambda timeout — no API Gateway 29s cap — and
writes the result back onto the pending RECO record.

This is why the recommendation is reliable despite slow free-tier latency: the
model gets up to ~55s here instead of ~26s inline. The API returns instantly
with a pending id; the dashboard polls until this flips the record to done.
"""
import model as reco_model
from common import RECO_PK, TABLE


def handler(event, context):
    requested_at = event["requested_at"]
    try:
        rec = reco_model.recommend(
            event["title"], event["duration_min"], event["slots"],
            event["academic"], event["community"], event["timezone"])
    except Exception as exc:  # noqa: BLE001 — record an honest error, never leave it pending
        print(f"[reco_worker] {requested_at} failed: {type(exc).__name__}: {exc}")
        TABLE.update_item(
            Key={"PK": RECO_PK, "SK": requested_at},
            UpdateExpression="SET #st = :st, #s = :src",
            ExpressionAttributeNames={"#st": "status", "#s": "source"},
            ExpressionAttributeValues={":st": "error", ":src": f"error: {type(exc).__name__}"},
        )
        return {"ok": False}

    TABLE.update_item(
        Key={"PK": RECO_PK, "SK": requested_at},
        UpdateExpression="SET #s = :src, reasoning = :r, ranked = :rk, #st = :st",
        ExpressionAttributeNames={"#s": "source", "#st": "status"},
        ExpressionAttributeValues={
            ":src": rec["source"], ":r": rec["reasoning"],
            ":rk": rec["ranked"], ":st": "done",
        },
    )
    print(f"[reco_worker] {requested_at} done via {rec['source']}, {len(rec['ranked'])} ranked")
    return {"ok": True}
