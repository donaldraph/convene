"""The model seam: given both calendars and a new-event request, recommend the
best conflict-free time slots. This is where the load-bearing AI lives.

The division of labour is deliberate. Deterministic code (conflicts.py, and
free_slots below) does what code should: compute which candidate slots are
actually free of hard conflicts. The MODEL does what code cannot fake: rank
those free slots by judgment a student actually cares about — protecting study
time around tests, avoiding back-to-back cross-campus hops, respecting
energy (a 7am slot is "free" but bad), keeping community events in sociable
hours — and explain the pick in plain language.

So we never ask the model "is this slot free" (code knows that for certain);
we ask "given these free slots and everything on both calendars, which is best
for this event, and why". No AI-washing of date math.

Wired to Google Gemini (gemini-3.5-flash by default; override with MODEL_ID).
Key from Secrets Manager. If the key is missing or the call fails, this returns
a clearly-labelled deterministic fallback (earliest free slot) so the endpoint
never lies about being AI when it is not.
"""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from typing import List, Optional, TypedDict

# Model gating on this key is fiddly (verified live 2026-07-31): gemini-2.5-flash
# and the *-latest 'lite' aliases 404, gemini-3.5-flash 503s hard under load,
# gemini-2.0-flash 429s. Two held up 3/3 with the response schema:
# gemini-flash-latest (sharper reasoning) and gemini-3.5-flash-lite (rock solid).
# So: primary is the sharp one, with the solid one as an automatic fallback
# before we ever drop to deterministic. Override both with env at deploy.
MODEL_ID = os.environ.get("MODEL_ID", "gemini-flash-latest")
MODEL_FALLBACKS = [m.strip() for m in
                   os.environ.get("MODEL_FALLBACKS", "gemini-3.5-flash-lite").split(",")
                   if m.strip()]
GEMINI_SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME", "convene/gemini")
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class Slot(TypedDict):
    start: str
    end: str


class Recommendation(TypedDict):
    source: str
    ranked: List[dict]
    reasoning: str


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["start", "end", "why"],
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["ranked", "reasoning"],
}

_PROMPT = """\
You are scheduling help for a student community group leader who juggles an
academic calendar and a community-events calendar. Speak to them directly as
"you". You must pick the best time to hold a NEW event.

The new event: {title}, duration {duration_minutes} minutes.

These candidate slots are ALREADY confirmed free of hard calendar conflicts by
deterministic code — you do not need to re-check availability, and you must
choose only from this list. Times are ISO 8601 in the calendar's timezone
({timezone}):
{slots}

For context, here is everything on both calendars in the window, so you can
reason about what sits near each slot (a slot right before a test, or
sandwiched between two community events across town, is free but poor):
Academic events:
{academic}
Community events:
{community}

Your job, using judgment plain date-math cannot:
1. ranked: order the candidate slots best-first. For each, copy its exact start
   and end from the list and add "why" — one sentence on the trade-off that
   sets its rank (protecting revision time before a test, avoiding a punishing
   gap between commitments, keeping the event in sociable hours, giving buffer
   after a class). Rank ALL provided slots.
2. reasoning: 2 to 4 sentences addressed to "you", naming your single best slot
   and the concrete reason it wins over the runner-up. Be specific with days
   and times; do not invent events that are not listed.

Choose only from the candidate slots. Never output a time not in the list.
"""


def free_slots(
    new_duration_min: int,
    academic: List[dict],
    community: List[dict],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    day_start_hour: int = 8,
    day_end_hour: int = 21,
    step_min: int = 30,
) -> List[Slot]:
    """Deterministic: candidate slots of the given length inside daytime hours
    that overlap NO timed event on either calendar. This is the certain part;
    the model only ranks what this returns."""
    busy = []
    for ev in list(academic) + list(community):
        if ev.get("all_day"):
            continue
        try:
            s = datetime.datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            e = datetime.datetime.fromisoformat(ev["end"].replace("Z", "+00:00"))
            busy.append((s, e))
        except (ValueError, KeyError):
            continue

    dur = datetime.timedelta(minutes=new_duration_min)
    step = datetime.timedelta(minutes=step_min)
    slots: List[Slot] = []
    cursor = window_start
    while cursor + dur <= window_end:
        h = cursor.hour + cursor.minute / 60
        end = cursor + dur
        end_h = end.hour + end.minute / 60 + (24 if end.date() > cursor.date() else 0)
        if h >= day_start_hour and end_h <= day_end_hour:
            if not any(cursor < b_end and b_start < end for b_start, b_end in busy):
                slots.append({"start": cursor.isoformat(), "end": end.isoformat()})
        cursor += step
    return slots


def _api_key() -> Optional[str]:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        from common import get_secret
        return get_secret(GEMINI_SECRET_NAME).get("api_key")
    except Exception:  # noqa: BLE001 — no secret / no access -> caller falls back
        return None


def _call_gemini(prompt: str, key: str, model_id: str) -> dict:
    url = f"{_API_BASE}/{model_id}:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            "temperature": 0.4,
        },
    }).encode("utf-8")
    last_err = None
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                payload = json.load(r)
            return json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (429, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last_err  # pragma: no cover


def _fallback(slots: List[Slot], source: str) -> Recommendation:
    """Honest deterministic fallback: earliest free slot, clearly not AI."""
    ranked = [{"start": s["start"], "end": s["end"],
               "why": "earliest available slot (deterministic fallback)"} for s in slots]
    best = slots[0]["start"] if slots else "none"
    return {
        "source": source,
        "ranked": ranked,
        "reasoning": f"[{source}] the model did not run, so this is the earliest "
                     f"free slot by the clock, not a judged recommendation. "
                     f"Best free slot: {best}.",
    }


def recommend(title: str, duration_min: int, slots: List[Slot],
              academic: List[dict], community: List[dict], timezone: str) -> Recommendation:
    """Rank free slots for a new event. Model-ranked when possible, honest
    deterministic fallback otherwise. Never claims AI it did not use."""
    if not slots:
        return {"source": "no-slots", "ranked": [],
                "reasoning": "No conflict-free slot of that length exists in the "
                             "window. Try a shorter event or a longer horizon."}

    key = _api_key()
    if not key:
        return _fallback(slots, "FALLBACK: no Gemini key available")

    def _fmt(events):
        return "\n".join(
            f"  - {e.get('summary', '(untitled)')}: {e['start']} to {e['end']}"
            f"{' (all day)' if e.get('all_day') else ''}" for e in events) or "  (none)"

    prompt = _PROMPT.format(
        title=title, duration_minutes=duration_min, timezone=timezone,
        slots="\n".join(f"  - {s['start']} to {s['end']}" for s in slots),
        academic=_fmt(academic), community=_fmt(community))

    # Try the sharp model first, then each fallback, before deterministic.
    valid = {s["start"] for s in slots}
    last_err = None
    for model_id in [MODEL_ID, *MODEL_FALLBACKS]:
        try:
            raw = _call_gemini(prompt, key, model_id)
        except Exception as exc:  # noqa: BLE001 — try the next model, then fall back
            last_err = exc
            continue
        ranked = [r for r in raw.get("ranked", []) if r.get("start") in valid]
        if ranked:
            return {"source": model_id, "ranked": ranked,
                    "reasoning": raw.get("reasoning", "")}
        last_err = last_err or "no valid slot in model output"
    reason = type(last_err).__name__ if isinstance(last_err, Exception) else str(last_err)
    return _fallback(slots, f"FALLBACK: all models failed ({reason})")
