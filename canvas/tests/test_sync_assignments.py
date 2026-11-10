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

    def test_attachments_are_linked_in_the_description(self):
        d = Path(self.tmp.name)
        write(d, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  description: <p>Submit a PDF.</p>\n"
            "  attachments: ['{stem}.pdf', 'student/{stem}.qmd']\n---\n"
        ))
        config, wanted = sa.wanted_assignments(self.config)
        hw3 = [w for w in wanted if w["name"] == "Homework 3"][0]
        self.assertEqual([p.name for p in hw3["attachments"]], ["hw3.pdf", "hw3.qmd"])

        folder = SimpleNamespace(
            get_files=lambda: [SimpleNamespace(display_name="hw3.pdf", id=42)]
        )
        links = sa.file_links(config, folder, wanted)
        self.assertEqual(links["hw3.pdf"], "https://example.instructure.com/courses/1/files/42")
        self.assertIsNone(links["hw3.qmd"])

        text = sa.with_attachments(hw3, links)["description"]
        self.assertTrue(text.startswith("<p>Submit a PDF.</p>"))
        self.assertIn('<a href="https://example.instructure.com/courses/1/files/42">hw3.pdf</a>', text)
        self.assertIn("(not uploaded yet)", text)

    def test_never_unpublishes_without_the_flag(self):
        item = {"name": "Homework 1", "published": False}
        live = SimpleNamespace(name="Homework 1", published=True)
        self.assertEqual(sa.changes(item, live), {})
        self.assertEqual(sa.changes(item, live, allow_unpublish=True), {"published": False})
        draft = SimpleNamespace(name="Homework 1", published=False)
        self.assertEqual(sa.changes({"name": "Homework 1", "published": True}, draft),
                         {"published": True})

    def test_lock_at_and_absent_times(self):
        d = Path(self.tmp.name)
        write(d, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  due_at: 2026-10-15T23:59:00-07:00\n"
            "  lock_at: 2026-10-16T23:59:00-07:00\n---\n"
        ))
        _, wanted = sa.wanted_assignments(self.config)
        by_name = {w["name"]: w for w in wanted}
        self.assertNotIn("lock_at", by_name["Homework 1"])
        payload = sa.to_api({"lock_at": by_name["Homework 3"]["lock_at"]})
        self.assertEqual(payload["lock_at"], "2026-10-17T06:59:00+00:00")
        live = SimpleNamespace(name="Homework 3", lock_at="2026-10-17T06:59:00Z")
        self.assertNotIn("lock_at", sa.changes(by_name["Homework 3"], live))

    def test_intro_appears_only_with_attachments(self):
        plain = {"description": "<p>Submit a PDF.</p>", "attachments": []}
        self.assertEqual(sa.with_attachments(plain, {}, "<p>Files:</p>"), plain)
        withfile = {"description": "<p>Submit a PDF.</p>", "attachments": [Path("hw.pdf")]}
        text = sa.with_attachments(withfile, {"hw.pdf": "u"}, "<p>Files:</p>")["description"]
        self.assertEqual(text.splitlines()[:2], ["<p>Submit a PDF.</p>", "<p>Files:</p>"])

    def test_api_payload_is_silent_and_serializable(self):
        _, wanted = sa.wanted_assignments(self.config)
        steps = sa.plan(FakeCourse([]), wanted, {"Homework": 7})
        payload = sa.to_api(steps[0][2])
        self.assertIs(payload["notify_of_update"], False)
        self.assertEqual(payload["due_at"], "2026-10-15T06:59:00+00:00")
        self.assertNotIn("_source", payload)

    def test_solution_releases_at_lock_at_by_default(self):
        d = self.tmp.name
        write(d, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  due_at: 2026-11-05T23:59:00-08:00\n"
            "  lock_at: 2026-11-06T23:59:00-08:00\n"
            "  solution: key/{stem}.pdf\n---\nbody\n"
        ))
        _, wanted = sa.wanted_assignments(self.config)
        hw3 = [w for w in wanted if w["name"] == "Homework 3"][0]
        self.assertEqual(hw3["solution"], Path(d).resolve() / "key" / "hw3.pdf")
        self.assertEqual(hw3["solution_unlock_at"], hw3["lock_at"])

    def test_solution_unlock_at_overrides_lock_at(self):
        write(self.tmp.name, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  lock_at: 2026-11-06T23:59:00-08:00\n"
            "  solution: k.pdf\n"
            "  solution_unlock_at: 2026-11-07T12:00:00-08:00\n---\nbody\n"
        ))
        _, wanted = sa.wanted_assignments(self.config)
        hw3 = [w for w in wanted if w["name"] == "Homework 3"][0]
        self.assertEqual(
            hw3["solution_unlock_at"],
            dt.datetime(2026, 11, 7, 20, 0, tzinfo=dt.timezone.utc),
        )

    def test_solution_without_any_release_time_is_refused(self):
        write(self.tmp.name, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n  solution: k.pdf\n---\nbody\n"
        ))
        with self.assertRaises(ValueError):
            sa.wanted_assignments(self.config)

    def test_self_grade_opens_at_lock_at_and_links_the_key(self):
        write(self.tmp.name, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  lock_at: 2026-11-06T23:59:00-08:00\n"
            "  solution: key/{stem}.pdf\n"
            "  self_grade:\n    name: Homework 3 self-grade\n"
            "    due_at: 2026-11-13T23:59:00-08:00\n    points_possible: 4\n---\nbody\n"
        ))
        _, wanted = sa.wanted_assignments(self.config)
        sg = [w for w in wanted if w["name"] == "Homework 3 self-grade"][0]
        hw3 = [w for w in wanted if w["name"] == "Homework 3"][0]
        self.assertIs(sg["published"], True)
        self.assertEqual(sg["unlock_at"], hw3["lock_at"])
        self.assertEqual(sg["attachments"], [hw3["solution"]])
        text = sa.with_attachments(sg, {"hw3.pdf": "u"}, "<p>Files:</p>")["description"]
        self.assertIn("<p>Solutions:</p>", text)
        self.assertIn("unlock_at", sa.MANAGED)

    def test_self_grade_without_a_key_is_refused(self):
        write(self.tmp.name, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  lock_at: 2026-11-06T23:59:00-08:00\n"
            "  self_grade:\n    name: Homework 3 self-grade\n---\nbody\n"
        ))
        with self.assertRaises(ValueError):
            sa.wanted_assignments(self.config)

    def test_self_grade_key_file_is_locked_until_it_opens(self):
        write(self.tmp.name, "hw3.qmd", (
            "---\ntitle: Homework 3\ncanvas:\n"
            "  lock_at: 2026-11-06T23:59:00-08:00\n"
            "  solution: k.pdf\n"
            "  self_grade:\n    name: Homework 3 self-grade\n---\nbody\n"
        ))
        write(self.tmp.name, "k.pdf", "x")
        config, wanted = sa.wanted_assignments(self.config)
        sg = [w for w in wanted if w["name"] == "Homework 3 self-grade"]
        updates = []

        class Course:
            def create_folder(self, *a, **k):
                return SimpleNamespace(upload=lambda p, **kw: (True, {"id": 9}))

            def get_folders(self):
                return []

            def get_file(self, i):
                return SimpleNamespace(update=lambda **kw: updates.append(kw))

        sa.upload_attachments(Course(), config, sg)
        self.assertEqual(updates[0]["unlock_at"], "2026-11-07T07:59:00+00:00")
        self.assertIs(updates[0]["hidden"], True)

    def test_solution_is_never_in_the_api_payload(self):
        payload = sa.to_api({"solution": Path("k.pdf"), "name": "x"})
        self.assertNotIn("solution", payload)


if __name__ == "__main__":
    unittest.main()
