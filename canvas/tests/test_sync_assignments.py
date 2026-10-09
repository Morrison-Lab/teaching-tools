"""Self-test for sync_assignments.py against a fake course; no network.

Run: python3 canvas/tests/test_sync_assignments.py
"""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_assignments as sa  # noqa: E402


class FakeCourse:
    def __init__(self, assignments):
        self.assignments = assignments

    def get_assignments(self, **kwargs):
        # The script must never ask for extra (possibly student) data.
        assert not kwargs, kwargs
        return self.assignments


def write(dirpath, name, text):
    path = Path(dirpath) / name
    path.write_text(text, encoding="utf-8")
    return path


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        write(d, "canvas.yml", (
            "url: https://example.instructure.com\n"
            "course_id: 1\n"
            "files: ['hw*.qmd']\n"
            "defaults:\n"
            "  submission_types: [online_upload]\n"
            "  assignment_group: Homework\n"
        ))
        write(d, "hw1.qmd", (
            "---\ntitle: Homework 1\ncanvas:\n"
            "  due_at: 2026-10-14T23:59:00-07:00\n"
            "  points_possible: 34\n  published: false\n---\nbody\n"
        ))
        write(d, "hw2.qmd", "---\ntitle: Homework 2\n---\nno canvas key\n")
        self.config = Path(d) / "canvas.yml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_only_files_with_canvas_key(self):
        _, wanted = sa.wanted_assignments(self.config)
        self.assertEqual([w["name"] for w in wanted], ["Homework 1"])
        self.assertEqual(
            wanted[0]["due_at"],
            dt.datetime(2026, 10, 15, 6, 59, tzinfo=dt.timezone.utc),
        )

    def test_create_then_unchanged_then_update(self):
        _, wanted = sa.wanted_assignments(self.config)
        groups = {"Homework": 7}

        steps = sa.plan(FakeCourse([]), wanted, groups)
        self.assertEqual(steps[0][0], "create")
        self.assertEqual(steps[0][2]["assignment_group_id"], 7)

        same = SimpleNamespace(
            name="Homework 1", due_at="2026-10-15T06:59:00Z",
            points_possible=34.0, published=False,
            submission_types=["online_upload"], assignment_group_id=7,
        )
        steps = sa.plan(FakeCourse([same]), wanted, groups)
        self.assertEqual(steps[0][0], "unchanged")

        moved = SimpleNamespace(**{**vars(same), "due_at": "2026-10-16T06:59:00Z"})
        steps = sa.plan(FakeCourse([moved]), wanted, groups)
        self.assertEqual(steps[0][0], "update")
        self.assertEqual(list(steps[0][2]), ["due_at"])

    def test_refuses_naive_time_and_unknown_group(self):
        with self.assertRaises(ValueError):
            sa.parse_time("2026-10-14T23:59:00")
        _, wanted = sa.wanted_assignments(self.config)
        with self.assertRaises(ValueError):
            sa.plan(FakeCourse([]), wanted, {})

    def test_refuses_ambiguous_match(self):
        _, wanted = sa.wanted_assignments(self.config)
        twin = SimpleNamespace(name="Homework 1")
        with self.assertRaises(ValueError):
            sa.plan(FakeCourse([twin, twin]), wanted, {"Homework": 7})

    def test_api_payload_is_silent_and_serializable(self):
        _, wanted = sa.wanted_assignments(self.config)
        steps = sa.plan(FakeCourse([]), wanted, {"Homework": 7})
        payload = sa.to_api(steps[0][2])
        self.assertIs(payload["notify_of_update"], False)
        self.assertEqual(payload["due_at"], "2026-10-15T06:59:00+00:00")
        self.assertNotIn("_source", payload)


if __name__ == "__main__":
    unittest.main()
