# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "canvasapi",
#     "pyyaml",
# ]
# ///
"""
Create or update Canvas assignments from the `canvas:` front matter of
Quarto (or any YAML-front-matter) files. Course-agnostic: the course's own
repository holds the config file and the front matter.

Run it again and nothing changes unless a file changed: an assignment is
matched by name, created if missing, and updated only in the fields that
differ. Without --apply it is a dry run that prints what it would do.

Usage:
    uv run sync_assignments.py path/to/canvas.yml            # dry run
    uv run sync_assignments.py path/to/canvas.yml --apply    # writes to Canvas

Config file (paths are relative to the config file):

    url: https://wwu.instructure.com
    course_id: 1906010
    files:
      - Homework/2026-fall-morrison/hw*.qmd
    defaults:                       # optional; applied to every assignment
      submission_types: [online_upload]
      allowed_extensions: [pdf]
      assignment_group: Homework    # looked up by name; must already exist

Front matter of each file:

    title: "Homework 1"
    canvas:
      name: "Homework 1"            # optional; defaults to `title`
      due_at: 2026-10-14T23:59:00-07:00   # must carry a UTC offset
      points_possible: 34
      published: false
      description: "<p>...</p>"     # optional; HTML

Token: the CANVAS_TOKEN environment variable if set, otherwise the macOS
keychain item named by --keychain-service (default `canvas-token`). The
token is never printed.

Student records: this script calls only the course, assignment-group and
assignment endpoints, never with an include[] parameter, so it reads no
roster, submission or grade. Keep it that way: those are FERPA education
records, and must not be pulled at all.
"""

import argparse
import datetime as dt
import glob
import os
import subprocess
import sys
from pathlib import Path

import yaml

# Fields the script manages, and how to compare them with what Canvas returns.
MANAGED = [
    "name",
    "due_at",
    "points_possible",
    "published",
    "description",
    "submission_types",
    "allowed_extensions",
    "assignment_group_id",
]


def read_front_matter(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def parse_time(value):
    """Return an aware datetime, or None. Refuse a time with no UTC offset."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        when = value
    else:
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError(f"due_at {value!r} has no UTC offset")
    return when.astimezone(dt.timezone.utc)


def wanted_assignments(config_path):
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    base = Path(config_path).resolve().parent
    defaults = config.get("defaults", {})
    wanted = []
    for pattern in config["files"]:
        for path in sorted(glob.glob(str(base / pattern))):
            meta = read_front_matter(path)
            spec = meta.get("canvas")
            if not spec:
                continue
            item = {**defaults, **spec}
            item.setdefault("name", meta.get("title"))
            if not item.get("name"):
                raise ValueError(f"{path}: no canvas.name and no title")
            item["due_at"] = parse_time(item.get("due_at"))
            item["_source"] = os.path.relpath(path, base)
            wanted.append(item)
    names = [w["name"] for w in wanted]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate assignment names: {sorted(dupes)}")
    return config, wanted


def normalize(field, value):
    if field == "due_at":
        return parse_time(value)
    if field in ("submission_types", "allowed_extensions"):
        return sorted(value or [])
    if field == "points_possible":
        return None if value is None else float(value)
    if field == "description":
        return (value or "").strip()
    return value


def changes(item, existing):
    """The managed fields whose wanted value differs from the existing one."""
    diff = {}
    for field in MANAGED:
        if field not in item:
            continue
        new = normalize(field, item[field])
        old = normalize(field, getattr(existing, field, None)) if existing else None
        if existing is None or new != old:
            diff[field] = item[field]
    return diff


def to_api(fields):
    out = dict(fields)
    if isinstance(out.get("due_at"), dt.datetime):
        out["due_at"] = out["due_at"].isoformat()
    out["notify_of_update"] = False
    return out


def plan(course, wanted, group_ids):
    """Return a list of (action, item, fields, existing) without writing."""
    existing, seen_twice = {}, set()
    for a in course.get_assignments():
        if a.name in existing:
            seen_twice.add(a.name)
        existing[a.name] = a
    clash = seen_twice & {w["name"] for w in wanted}
    if clash:
        raise ValueError(f"Canvas has more than one assignment named {sorted(clash)}")
    steps = []
    for item in wanted:
        item = dict(item)
        group = item.pop("assignment_group", None)
        if group is not None:
            if group not in group_ids:
                raise ValueError(f"no assignment group named {group!r}")
            item["assignment_group_id"] = group_ids[group]
        old = existing.get(item["name"])
        diff = changes(item, old)
        action = "create" if old is None else ("update" if diff else "unchanged")
        steps.append((action, item, diff, old))
    return steps


def describe(field, value):
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if field == "description":
        text = str(value or "")
        return text if len(text) <= 60 else text[:57] + "..."
    return repr(value)


def report(steps):
    for action, item, diff, old in steps:
        print(f"{action:9} {item['name']}  ({item['_source']})")
        for field, value in diff.items():
            before = ""
            if old is not None:
                before = f"{describe(field, getattr(old, field, None))} -> "
            print(f"          {field}: {before}{describe(field, value)}")


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
    parser.add_argument("config", help="the course's canvas.yml")
    parser.add_argument("--apply", action="store_true", help="write to Canvas")
    parser.add_argument("--keychain-service", default="canvas-token")
    args = parser.parse_args(argv)

    from canvasapi import Canvas

    config, wanted = wanted_assignments(args.config)
    canvas = Canvas(config["url"], get_token(args.keychain_service))
    course = canvas.get_course(config["course_id"])
    group_ids = {g.name: g.id for g in course.get_assignment_groups()}

    print(f"Course: {course.name} ({course.id})")
    print(f"Assignment groups: {', '.join(sorted(group_ids)) or '(none)'}\n")
    steps = plan(course, wanted, group_ids)
    report(steps)

    if not args.apply:
        print("\nDry run: nothing was written. Re-run with --apply to write.")
        return
    for action, item, diff, old in steps:
        if action == "create":
            course.create_assignment(to_api(diff))
        elif action == "update":
            old.edit(assignment=to_api(diff))
    print("\nApplied.")


if __name__ == "__main__":
    main()
