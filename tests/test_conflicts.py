"""Unit tests for the pure conflict engine. Run: python3 -m unittest discover tests
No AWS, no network - these prove the interval math before anything touches a
real calendar."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "lambdas"))

import conflicts  # noqa: E402


def timed(eid, start, end, summary="x"):
    return {"id": eid, "summary": summary, "start": start, "end": end,
            "all_day": False, "location": None, "url": None}


def all_day(eid, start, end, summary="x"):
    return {"id": eid, "summary": summary, "start": start, "end": end,
            "all_day": True, "location": None, "url": None}


class TestHardConflicts(unittest.TestCase):
    def test_plain_overlap(self):
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T12:00:00+01:00")
        c = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T13:00:00+01:00")
        out = conflicts.detect([a], [c])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "hard")

    def test_containment(self):
        a = timed("a1", "2026-08-01T09:00:00+01:00", "2026-08-01T17:00:00+01:00")
        c = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T12:00:00+01:00")
        self.assertEqual(conflicts.detect([a], [c])[0]["type"], "hard")

    def test_no_overlap(self):
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T11:00:00+01:00")
        c = timed("c1", "2026-08-01T12:00:00+01:00", "2026-08-01T13:00:00+01:00")
        self.assertEqual(conflicts.detect([a], [c]), [])

    def test_touching_edges_do_not_conflict(self):
        # Back-to-back is legal: end == start is NOT an overlap.
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T11:00:00+01:00")
        c = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T12:00:00+01:00")
        self.assertEqual(conflicts.detect([a], [c]), [])

    def test_cross_timezone_overlap(self):
        # 10:00 Lagos (+01) == 09:00 UTC; a 09:30Z event overlaps it.
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T11:00:00+01:00")
        c = timed("c1", "2026-08-01T09:30:00+00:00", "2026-08-01T10:30:00+00:00")
        self.assertEqual(conflicts.detect([a], [c])[0]["type"], "hard")


class TestSameDayConflicts(unittest.TestCase):
    def test_all_day_vs_timed_same_date(self):
        a = all_day("a1", "2026-08-03", "2026-08-04", "Exam week starts")
        c = timed("c1", "2026-08-03T15:00:00+01:00", "2026-08-03T17:00:00+01:00")
        out = conflicts.detect([a], [c])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "same_day")

    def test_all_day_vs_timed_other_date(self):
        a = all_day("a1", "2026-08-03", "2026-08-04")
        c = timed("c1", "2026-08-04T15:00:00+01:00", "2026-08-04T16:00:00+01:00")
        self.assertEqual(conflicts.detect([a], [c]), [])

    def test_multiday_all_day_spans(self):
        # Aug 3-5 inclusive (end date exclusive per Google).
        a = all_day("a1", "2026-08-03", "2026-08-06")
        c = timed("c1", "2026-08-05T10:00:00+01:00", "2026-08-05T11:00:00+01:00")
        self.assertEqual(conflicts.detect([a], [c])[0]["type"], "same_day")

    def test_two_all_day_sharing_a_date(self):
        a = all_day("a1", "2026-08-03", "2026-08-05")
        c = all_day("c1", "2026-08-04", "2026-08-06")
        self.assertEqual(conflicts.detect([a], [c])[0]["type"], "same_day")


class TestDeterminism(unittest.TestCase):
    def test_stable_ids_across_reruns(self):
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T12:00:00+01:00")
        c = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T13:00:00+01:00")
        id1 = conflicts.detect([a], [c])[0]["id"]
        id2 = conflicts.detect([a], [c])[0]["id"]
        self.assertEqual(id1, id2)

    def test_id_symmetric_in_pair_order(self):
        a = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T12:00:00+01:00")
        c = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T13:00:00+01:00")
        self.assertEqual(conflicts.conflict_id(a, c), conflicts.conflict_id(c, a))

    def test_multiple_conflicts_sorted_and_distinct(self):
        a1 = timed("a1", "2026-08-01T10:00:00+01:00", "2026-08-01T12:00:00+01:00")
        a2 = timed("a2", "2026-08-02T10:00:00+01:00", "2026-08-02T12:00:00+01:00")
        c1 = timed("c1", "2026-08-01T11:00:00+01:00", "2026-08-01T13:00:00+01:00")
        c2 = timed("c2", "2026-08-02T11:00:00+01:00", "2026-08-02T13:00:00+01:00")
        out = conflicts.detect([a1, a2], [c1, c2])
        self.assertEqual(len(out), 2)
        self.assertEqual(len({x["id"] for x in out}), 2)
        self.assertEqual([x["id"] for x in out], sorted(x["id"] for x in out))


if __name__ == "__main__":
    unittest.main()
