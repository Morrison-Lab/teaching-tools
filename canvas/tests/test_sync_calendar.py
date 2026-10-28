"""Self-test for sync_calendar.py against a fake Canvas; no network.

Run: python3 canvas/tests/test_sync_calendar.py
"""

import datetime as dt
import sys
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_calendar as sc  # noqa: E402

CONFIG = """
course_id: 1
timezone: America/Los_Angeles
events:
  - key: class
    title: Class
    time: "12:00-13:00"
    location: Room 1
    repeat: {weekdays: [Mon, Wed], from: 2026-11-09, to: 2026-11-18, except: [2026-11-11]}
  - key: midterm
    title: Midterm
    date: 2026-11-13
    time: "12:00-13:00"
  - key: holiday
    title: No class
    date: 2026-11-11
"""


def wanted_from(text=CONFIG):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "events.yml"
        path.write_text(text)
        return sc.wanted_events(path)[1]


def canvas_event(key, item, **over):
    fields = dict(
        title=item["title"], location_name=item["location_name"], all_day=item["all_day"],
        start_at=item["start_at"].astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        end_at=item["end_at"].astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        description=item["description"],
    )
    fields.update(over)
    event = SimpleNamespace(**fields)
    event.edits, event.deleted = [], False
    event.edit = lambda **kw: event.edits.append(kw)
    event.delete = lambda: setattr(event, "deleted", True)
    return event


class FakeCanvas:
    def __init__(self, events):
        self.events, self.created = events, []

    def get_calendar_events(self, **kwargs):
        assert set(kwargs) == {"context_codes", "type", "start_date", "end_date"}, kwargs
        return self.events

    def create_calendar_event(self, event):
        self.created.append(event)


class SyncCalendarTest(unittest.TestCase):
    def test_expansion_skips_excepted_dates(self):
        self.assertEqual(
            sorted(k for k in wanted_from() if k.startswith("class-")),
            ["class-2026-11-09", "class-2026-11-16", "class-2026-11-18"])

    def test_times_carry_the_timezone(self):
        item = wanted_from()["midterm"]
        self.assertEqual(item["start_at"].utcoffset(), dt.timedelta(hours=-8))
        self.assertTrue(wanted_from()["holiday"]["all_day"])

    def test_first_run_creates_everything_and_rerun_is_empty(self):
        wanted = wanted_from()
        steps = sc.plan(wanted, {}, False)
        self.assertEqual({s[0] for s in steps}, {"create"})
        self.assertEqual(len(steps), len(wanted))
        events = {k: canvas_event(k, v) for k, v in wanted.items()}
        self.assertEqual(sc.plan(wanted, events, False), [])

    def test_moved_event_is_updated_not_duplicated(self):
        wanted = wanted_from()
        events = {k: canvas_event(k, v) for k, v in wanted.items()}
        events["midterm"] = canvas_event("midterm", wanted["midterm"], start_at="2026-11-09T20:00:00Z")
        steps = sc.plan(wanted, events, False)
        self.assertEqual([(s[0], s[1]) for s in steps], [("update", "midterm")])
        self.assertEqual(list(steps[0][2]), ["start_at"])

    def test_stale_event_is_deleted_only_when_allowed(self):
        wanted = wanted_from()
        events = {k: canvas_event(k, v) for k, v in wanted.items()}
        events["gone"] = canvas_event("gone", wanted["midterm"])
        self.assertEqual(sc.plan(wanted, events, False)[0][0], "stale")
        self.assertEqual(sc.plan(wanted, events, True)[0][0], "delete")

    def test_hand_made_events_are_never_matched(self):
        wanted = wanted_from()
        by_hand = canvas_event("x", wanted["midterm"], description="<p>mine</p>")
        canvas = FakeCanvas([by_hand])
        self.assertEqual(sc.existing_events(canvas, 1, wanted), {})

    def test_apply_writes_through_the_api(self):
        wanted = wanted_from()
        events = {"midterm": canvas_event("midterm", wanted["midterm"], title="Old")}
        events["gone"] = canvas_event("gone", wanted["midterm"])
        canvas = FakeCanvas([])
        steps = sc.plan(wanted, events, True)
        with redirect_stdout(StringIO()):
            sc.report(steps, len(wanted))
        sc.apply(canvas, 1, steps, events)
        self.assertEqual(len(canvas.created), len(wanted) - 1)
        self.assertEqual(canvas.created[0]["context_code"], "course_1")
        self.assertEqual(events["midterm"].edits, [{"calendar_event": {"title": "Midterm"}}])
        self.assertTrue(events["gone"].deleted)

    def test_duplicate_keys_stop_the_run(self):
        with self.assertRaises(SystemExit):
            wanted_from(CONFIG + "  - {key: holiday, title: X, date: 2026-12-01}\n")


if __name__ == "__main__":
    unittest.main()
