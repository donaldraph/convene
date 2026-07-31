"""Unit tests for the single-calendar tag classifier."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "lambdas"))

import classify  # noqa: E402


def ev(eid, summary):
    return {"id": eid, "summary": summary, "start": "2026-08-01T12:00:00Z",
            "end": "2026-08-01T13:00:00Z", "all_day": False}


class TestSplitByTag(unittest.TestCase):
    def test_basic_split(self):
        events = [ev("1", "Academic: Algorithms"), ev("2", "Outreach: AWS session"),
                  ev("3", "academic lab"), ev("4", "tour")]
        academic, community = classify.split_by_tag(events, "academic")
        self.assertEqual([e["id"] for e in academic], ["1", "3"])
        self.assertEqual([e["id"] for e in community], ["2", "4"])

    def test_case_insensitive(self):
        academic, community = classify.split_by_tag([ev("1", "ACADEMIC exam")], "academic")
        self.assertEqual(len(academic), 1)
        self.assertEqual(len(community), 0)

    def test_untitled_is_community(self):
        academic, community = classify.split_by_tag([{"id": "1", "summary": ""}], "academic")
        self.assertEqual(len(community), 1)

    def test_order_preserved(self):
        events = [ev("a", "outreach"), ev("b", "academic"), ev("c", "outreach")]
        _, community = classify.split_by_tag(events)
        self.assertEqual([e["id"] for e in community], ["a", "c"])

    def test_custom_tag(self):
        academic, community = classify.split_by_tag(
            [ev("1", "Class: DB"), ev("2", "Meetup")], academic_tag="Class")
        self.assertEqual(len(academic), 1)
        self.assertEqual(academic[0]["id"], "1")


if __name__ == "__main__":
    unittest.main()
