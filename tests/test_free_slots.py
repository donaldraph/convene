"""Unit tests for the deterministic free-slot finder. The MODEL ranks slots;
this code decides which slots are genuinely free, so it must be exact."""
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "lambdas"))

import model  # noqa: E402

UTC = datetime.timezone.utc


def dt(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=UTC)


def timed(eid, start, end):
    return {"id": eid, "summary": eid, "start": start.isoformat(),
            "end": end.isoformat(), "all_day": False}


class TestFreeSlots(unittest.TestCase):
    def test_avoids_busy_interval(self):
        # Busy 10-12 on Aug 1; a 60-min slot must never overlap it.
        busy = [timed("x", dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))]
        slots = model.free_slots(60, busy, [], dt(2026, 8, 1, 8), dt(2026, 8, 1, 18))
        for s in slots:
            start = datetime.datetime.fromisoformat(s["start"])
            end = datetime.datetime.fromisoformat(s["end"])
            self.assertFalse(start < dt(2026, 8, 1, 12) and dt(2026, 8, 1, 10) < end)

    def test_respects_daytime_hours(self):
        slots = model.free_slots(60, [], [], dt(2026, 8, 1, 0), dt(2026, 8, 2, 0),
                                 day_start_hour=8, day_end_hour=21)
        for s in slots:
            self.assertGreaterEqual(datetime.datetime.fromisoformat(s["start"]).hour, 8)
            self.assertLessEqual(datetime.datetime.fromisoformat(s["end"]).hour, 21)

    def test_both_calendars_block(self):
        acad = [timed("a", dt(2026, 8, 1, 9), dt(2026, 8, 1, 10))]
        comm = [timed("c", dt(2026, 8, 1, 14), dt(2026, 8, 1, 15))]
        slots = model.free_slots(60, acad, comm, dt(2026, 8, 1, 8), dt(2026, 8, 1, 17))
        starts = {s["start"] for s in slots}
        self.assertNotIn(dt(2026, 8, 1, 9).isoformat(), starts)
        self.assertNotIn(dt(2026, 8, 1, 14).isoformat(), starts)

    def test_all_day_events_do_not_block(self):
        # An all-day academic event should not remove every timed slot that day.
        allday = [{"id": "e", "summary": "Exam week", "start": "2026-08-01",
                   "end": "2026-08-02", "all_day": True}]
        slots = model.free_slots(60, allday, [], dt(2026, 8, 1, 8), dt(2026, 8, 1, 18))
        self.assertGreater(len(slots), 0)

    def test_no_slot_when_fully_booked(self):
        busy = [timed("x", dt(2026, 8, 1, 8), dt(2026, 8, 1, 21))]
        slots = model.free_slots(60, busy, [], dt(2026, 8, 1, 8), dt(2026, 8, 1, 21))
        self.assertEqual(slots, [])

    def test_recommend_no_slots_is_honest(self):
        rec = model.recommend("Party", 60, [], [], [], "Africa/Lagos")
        self.assertEqual(rec["source"], "no-slots")
        self.assertEqual(rec["ranked"], [])

    def test_recommend_falls_back_without_key(self):
        # No GEMINI_API_KEY in the test env and no boto3 secret -> honest fallback,
        # never a claim of AI.
        slots = [{"start": dt(2026, 8, 1, 9).isoformat(), "end": dt(2026, 8, 1, 10).isoformat()}]
        rec = model.recommend("Study jam", 60, slots, [], [], "Africa/Lagos")
        self.assertTrue(rec["source"].startswith("FALLBACK"))
        self.assertEqual(len(rec["ranked"]), 1)


class TestShortlist(unittest.TestCase):
    def test_caps_and_spreads(self):
        # 3 days of dense half-hourly slots -> at most per_day*days, <= max_total.
        slots = []
        for d in range(1, 4):
            for h in range(8, 20):
                slots.append({"start": dt(2026, 8, d, h).isoformat(),
                              "end": dt(2026, 8, d, h + 1).isoformat()})
        picked = model.shortlist(slots, per_day=3, max_total=18)
        self.assertLessEqual(len(picked), 9)
        days = {p["start"][:10] for p in picked}
        self.assertEqual(len(days), 3)  # every day represented

    def test_total_cap_wins(self):
        slots = []
        for d in range(1, 11):
            for h in range(8, 20):
                slots.append({"start": dt(2026, 8, d, h).isoformat(),
                              "end": dt(2026, 8, d, h + 1).isoformat()})
        self.assertLessEqual(len(model.shortlist(slots, per_day=3, max_total=18)), 18)

    def test_thin_day_kept_whole(self):
        slots = [{"start": dt(2026, 8, 1, 9).isoformat(), "end": dt(2026, 8, 1, 10).isoformat()}]
        self.assertEqual(len(model.shortlist(slots, per_day=3)), 1)


if __name__ == "__main__":
    unittest.main()
