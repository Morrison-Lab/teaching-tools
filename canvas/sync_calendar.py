# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "canvasapi",
#     "pyyaml",
# ]
# ///
"""
Create, update or remove Canvas course calendar events from a YAML (or JSON, which is valid YAML) events file.
Course-agnostic: the course's own repository holds the events file.

Run it again and nothing changes unless the file changed. Each event the
script makes ends its description with a line `Synced event: <key>`, and an
event is matched by that key, so a moved event is updated, not duplicated.
Events without that line (made by hand in Canvas) are never touched.
An event whose key is no longer in the file is deleted only with
--allow-delete. Without --apply it is a dry run that prints what it would do
and writes nothing.

Usage:
    uv run sync_calendar.py path/to/calendar-events.yml            # dry run
    uv run sync_calendar.py path/to/calendar-events.yml --apply    # writes to Canvas

Events file:

    url: https://wwu.instructure.com
    course_id: 1906010
    timezone: America/Los_Angeles
    events:
      - key: midterm-1               # stable id; never reuse it
        title: "Midterm 1"
        date: 2026-10-30
        time: "12:00-13:00"          # optional; omit for an all-day event
        location: "Kaiser Borsari Hall 311"   # optional
        description: "<p>...</p>"    # optional; HTML
      - key: class
        title: "DATA 571 class"
        time: "12:00-13:00"
        repeat:                      # one event per listed weekday in the range
          weekdays: [Mon, Tue, Wed, Fri]
          from: 2026-09-23
          to: 2026-12-04
          except: [2026-11-11]       # dates with no event
        # `key` becomes class-2026-09-23, class-2026-09-25, ...

Token: the CANVAS_TOKEN environment variable if set, otherwise the macOS
keychain item named by --keychain-service (default `canvas-token`). The
token is never printed.

Student records: this script calls only the calendar-event endpoints, with no
include[], student_id or user_id parameter, so it reads no roster, submission
or grade. Keep it that way: those are FERPA education records, and must not
be pulled at all.
"""

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MARKER = re.compile(r"Synced event: ([A-Za-z0-9._-]+)")


def marker_html(key):
    return f"<p><small>Synced event: {key}</small></p>"


def as_date(value):
    if isinstance(value, dt.datetime):
        sys.exit(f"Expected a date, got a datetime: {value}")
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def expand(event):
    """Yield (key, date) for one entry of the events file."""
    repeat = event.get("repeat")
    if not repeat:
        yield event["key"], as_date(event["date"])
        return
    days = {WEEKDAYS.index(d) for d in repeat["weekdays"]}
    skip = {as_date(d) for d in repeat.get("except", [])}
    day, last = as_date(repeat["from"]), as_date(repeat["to"])
    while day <= last:
        if day.weekday() in days and day not in skip:
            yield f"{event['key']}-{day.isoformat()}", day
        day += dt.timedelta(days=1)


def wanted_events(path):
    config = yaml.safe_load(Path(path).read_text())
    tz = ZoneInfo(config.get("timezone", "America/Los_Angeles"))
    wanted = {}
    for event in config["events"]:
        for key, day in expand(event):
            if key in wanted:
                sys.exit(f"Duplicate event key {key!r}")
            item = {
                "title": event["title"],
                "location_name": event.get("location", ""),
                "description": (event.get("description", "") + marker_html(key)),
            }
            if event.get("time"):
                start, end = (dt.time.fromisoformat(t) for t in event["time"].split("-"))
                item["start_at"] = dt.datetime.combine(day, start, tz)
                item["end_at"] = dt.datetime.combine(day, end, tz)
                item["all_day"] = False
            else:
                item["start_at"] = item["end_at"] = dt.datetime.combine(day, dt.time(), tz)
                item["all_day"] = True
            wanted[key] = item
    return config, wanted


def parse_utc(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def existing_events(canvas, course_id, wanted):
    """Map key -> Canvas event, for events this script made."""
    stamps = [w["start_at"] for w in wanted.values()] or [dt.datetime.now(dt.timezone.utc)]
    found = canvas.get_calendar_events(
        context_codes=[f"course_{course_id}"],
        type="event",
        start_date=(min(stamps).date() - dt.timedelta(days=366)).isoformat(),
        end_date=(max(stamps).date() + dt.timedelta(days=366)).isoformat(),
    )
    events = {}
    for event in found:
        match = MARKER.search(getattr(event, "description", "") or "")
        if match:
            if match.group(1) in events:
                sys.exit(f"Two Canvas events carry the key {match.group(1)!r}; fix by hand.")
            events[match.group(1)] = event
    return events


def differences(item, event):
    out = {}
    if event.title != item["title"]:
        out["title"] = item["title"]
    if (event.location_name or "") != item["location_name"]:
        out["location_name"] = item["location_name"]
    if bool(event.all_day) != item["all_day"]:
        out["all_day"] = item["all_day"]
    for field in ("start_at", "end_at"):
        if parse_utc(getattr(event, field)) != item[field]:
            out[field] = item[field]
    # Canvas sanitizes the description's HTML, so compare the marker and text only.
    if MARKER.search(event.description or "") and _words(event.description) != _words(item["description"]):
        out["description"] = item["description"]
    return out


def _words(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def iso(value):
    return value.isoformat() if isinstance(value, dt.datetime) else value


def plan(wanted, events, allow_delete):
    steps = []
    for key, item in wanted.items():
        if key not in events:
            steps.append(("create", key, item))
        else:
            changed = differences(item, events[key])
            if changed:
                steps.append(("update", key, changed))
    for key in events:
        if key not in wanted:
            steps.append(("delete" if allow_delete else "stale", key, None))
    return steps


def report(steps, total):
    counts = {}
    for kind, key, fields in steps:
        counts[kind] = counts.get(kind, 0) + 1
        print(f"  {kind.upper():7} {key}")
        for field, value in (fields or {}).items():
            if field != "description":
                print(f"          {field}: {iso(value)}")
    unchanged = total - counts.get("create", 0) - counts.get("update", 0)
    print(f"\n{counts.get('create', 0)} to create, {counts.get('update', 0)} to update, "
          f"{counts.get('delete', 0)} to delete, {counts.get('stale', 0)} stale "
          f"(not deleted; use --allow-delete), {unchanged} unchanged")


def apply(canvas, course_id, steps, events):
    for kind, key, fields in steps:
        if kind == "create":
            canvas.create_calendar_event(
                {"context_code": f"course_{course_id}",
                 **{k: iso(v) for k, v in fields.items()}})
        elif kind == "update":
            events[key].edit(calendar_event={k: iso(v) for k, v in fields.items()})
        elif kind == "delete":
            events[key].delete()


def get_token(service):
    token = os.environ.get("CANVAS_TOKEN")
    if token:
        return token.strip()
    if sys.platform != "darwin":
        sys.exit("Set CANVAS_TOKEN, or run on a Mac with the token in the keychain.")
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"No keychain item named {service!r}; see the docstring.")
    return result.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("events", help="the course's calendar events YAML file")
    parser.add_argument("--apply", action="store_true", help="write to Canvas")
    parser.add_argument("--allow-delete", action="store_true",
                        help="delete synced events that are no longer in the file")
    parser.add_argument("--keychain-service", default="canvas-token")
    args = parser.parse_args(argv)

    from canvasapi import Canvas

    config, wanted = wanted_events(args.events)
    canvas = Canvas(config["url"], get_token(args.keychain_service))
    events = existing_events(canvas, config["course_id"], wanted)
    steps = plan(wanted, events, args.allow_delete)
    report(steps, len(wanted))
    if not args.apply:
        print("\nDry run; nothing written. Add --apply to write.")
        return
    apply(canvas, config["course_id"], steps, events)
    print("\nApplied.")


if __name__ == "__main__":
    main()
