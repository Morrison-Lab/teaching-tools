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
differ. Attachments are uploaded to one Canvas Files folder, replacing any
file of the same name, and linked from the end of the description; they are
re-uploaded on every --apply run, into a folder created hidden (reachable by
link only). Without --apply it is a dry run that prints what it would do
and writes nothing. An assignment already published in Canvas is never
unpublished unless --allow-unpublish is given.

Solutions: an optional `solution:` path in a file's `canvas:` block (or in
`defaults`; `{stem}` as for attachments) uploads that answer key to the Canvas
Files folder `<solutions_folder>/<file stem>` (default `Solutions/hw3`) and
(hidden: link-only, never listed in the student Files tab) and sets the file's
`unlock_at`, so its link opens only from the release time on, with no one
having to remember to. Link the key from an assignment that opens at that
time, such as the self-grade. The time is `solution_unlock_at` if given, else
the assignment's `lock_at` (when submissions close). With neither, the script
stops. The dry run lists each key and its release time. The release time is configurable per assignment
through `solution_unlock_at`.

Self-grade: an optional `self_grade:` block in a file's `canvas:` block
(`name`, required; `due_at`, `points_possible` and `description`, optional) makes a second
assignment that opens, published, at the homework's `lock_at` (its `unlock_at`)
and links the homework's `solution:` key in its description, like the
attachments above. A self-grade tells students to use the posted solutions, so
the key is uploaded before any assignment is written, and a `self_grade:` with
no `solution:` or no `lock_at` is refused. The key is then shared through the
self-grade, so it is not also put in the Solutions folder; its file is locked
until the self-grade opens.

Usage:
    uv run sync_assignments.py path/to/canvas.yml            # dry run
    uv run sync_assignments.py path/to/canvas.yml --apply    # writes to Canvas

Config file (paths are relative to the config file):

    url: https://wwu.instructure.com
    course_id: 1906010
    files:
      - Homework/2026-fall-morrison/hw*.qmd
    attachments_folder: Homework    # Canvas Files folder for attachments
    attachments_intro: "<p>...</p>" # HTML put before the links, if any
    defaults:                       # optional; applied to every assignment
      submission_types: [online_upload]
      allowed_extensions: [pdf]
      assignment_group: Homework    # looked up by name; must already exist
      description: "<p>...</p>"     # HTML; attachment links are appended
      attachments:                  # {stem} is the source file's name, no suffix
        - _output/{stem}.pdf

Front matter of each file:

    title: "Homework 1"
    canvas:
      name: "Homework 1"            # optional; defaults to `title`
      due_at: 2026-10-14T23:59:00-07:00   # must carry a UTC offset
      lock_at: 2026-10-15T23:59:00-07:00  # optional; submissions close
      points_possible: 34
      published: false
      description: "<p>...</p>"     # optional; HTML
      solution: _output/solution/Homework/2026-fall-morrison/{stem}.pdf
      solution_unlock_at: 2026-11-06T23:59:00-08:00   # optional; default lock_at

Token: the CANVAS_TOKEN environment variable if set, otherwise the macOS
keychain item named by --keychain-service (default `canvas-token`). The
token is never printed.

Student records: this script calls only the course, assignment-group,
assignment, folder and file endpoints, never with an include[] parameter, so it reads no
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
    "lock_at",
    "unlock_at",
    "points_possible",
    "published",
    "description",
    "submission_types",
    "allowed_extensions",
    "assignment_group_id",
]
TIMES = ("due_at", "lock_at", "unlock_at", "solution_unlock_at")


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
        raise ValueError(f"time {value!r} has no UTC offset")
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
            for field in TIMES:
                if field in item:
                    item[field] = parse_time(item[field])
            item["_source"] = os.path.relpath(path, base)
            stem = Path(path).stem
            item["attachments"] = [
                base / a.format(stem=stem) for a in item.get("attachments", [])
            ]
            if item.get("solution"):
                item["solution"] = base / item["solution"].format(stem=stem)
                release = item.get("solution_unlock_at") or item.get("lock_at")
                if release is None:
                    raise ValueError(
                        f"{path}: solution needs solution_unlock_at or lock_at"
                    )
                item["solution_unlock_at"] = release
            wanted.append(item)
            if spec.get("self_grade"):
                item["_has_self_grade"] = True
                wanted.append(self_grade_item(item, spec["self_grade"], defaults, base, stem))
    names = [w["name"] for w in wanted]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate assignment names: {sorted(dupes)}")
    return config, wanted


def self_grade_item(homework, spec, defaults, base, stem):
    """The self-grade assignment for `homework`, which opens when the homework locks.

    The self-grade tells students to grade against the posted solutions, so it must
    link the key: the key is its one attachment, uploaded before any assignment is
    written, and a self-grade with no `solution` is refused, never published bare.
    """
    if not homework.get("solution"):
        raise ValueError(
            f"{homework['_source']}: self_grade needs a solution: the self-grade links it"
        )
    if homework.get("lock_at") is None:
        raise ValueError(f"{homework['_source']}: self_grade needs lock_at to open at")
    item = {
        k: v for k, v in defaults.items()
        if k in ("assignment_group", "submission_types", "allowed_extensions")
    }
    item.update(spec)
    for field in TIMES:
        if field in item:
            item[field] = parse_time(item[field])
    item.update(
        published=True,
        unlock_at=homework["lock_at"],
        attachments=[homework["solution"]],
        attachments_intro="<p>Solutions:</p>",
        _source=homework["_source"],
    )
    if not item.get("name"):
        raise ValueError(f"{homework['_source']}: self_grade needs a name")
    return item


def normalize(field, value):
    if field in TIMES:
        return parse_time(value)
    if field in ("submission_types", "allowed_extensions"):
        return sorted(value or [])
    if field == "points_possible":
        return None if value is None else float(value)
    if field == "description":
        return (value or "").strip()
    return value


def changes(item, existing, allow_unpublish=False):
    """The managed fields whose wanted value differs from the existing one.

    An assignment already published in Canvas is never unpublished unless
    allow_unpublish is set: it may have been published by hand on release
    day, and Canvas refuses to unpublish one that has submissions.
    """
    diff = {}
    for field in MANAGED:
        if field not in item:
            continue
        if (field == "published" and not allow_unpublish and existing is not None
                and getattr(existing, "published", False) and not item[field]):
            continue
        new = normalize(field, item[field])
        old = normalize(field, getattr(existing, field, None)) if existing else None
        if existing is None or new != old:
            diff[field] = item[field]
    return diff


def find_folder(course, path):
    """The course folder at `path` (relative to the course's root), or None."""
    full = "course files" + (f"/{path.strip('/')}" if path.strip("/") else "")
    for folder in course.get_folders():
        if folder.full_name == full:
            return folder
    return None


def file_links(config, folder, wanted):
    """Map each attachment's file name to its Canvas URL, or None if not uploaded."""
    present = {}
    if folder is not None:
        present = {f.display_name: f.id for f in folder.get_files()}
    root = f"{config['url'].rstrip('/')}/courses/{config['course_id']}/files"
    links = {}
    for item in wanted:
        for path in item["attachments"]:
            file_id = present.get(path.name)
            links[path.name] = f"{root}/{file_id}" if file_id else None
    return links


def with_attachments(item, links, intro=""):
    """Append `intro` and links to the item's attachments to its description."""
    if not item["attachments"]:
        return item
    intro = item.get("attachments_intro", intro)
    rows = []
    for path in item["attachments"]:
        url = links.get(path.name) or "(not uploaded yet)"
        rows.append(f'<li><a href="{url}">{path.name}</a></li>')
    item = dict(item)
    parts = [(item.get("description") or "").strip(), intro.strip(), "<ul>", *rows, "</ul>"]
    item["description"] = "\n".join(p for p in parts if p)
    return item


def upload_attachments(course, config, wanted):
    """Upload every attachment, replacing a file of the same name. Returns the folder."""
    path = config.get("attachments_folder", "")
    folder = find_folder(course, path)
    if folder is None:
        parent, _, name = path.strip("/").rpartition("/")
        # Hidden: its files open from the assignment's links but are not listed
        # in the Files tab, so an unpublished assignment's files stay out of sight.
        folder = course.create_folder(name, parent_folder_path=parent, hidden=True)
    for item in wanted:
        for attachment in item["attachments"]:
            ok, response = folder.upload(str(attachment), on_duplicate="overwrite")
            if not ok:
                sys.exit(f"Upload of {attachment.name} failed: {response}")
            print(f"uploaded  {attachment.name}")
            if item.get("unlock_at"):
                # An assignment that opens later (a self-grade) must not expose
                # its key by direct link before then.
                course.get_file(response["id"]).update(
                    unlock_at=item["unlock_at"].isoformat(), locked=False, hidden=True
                )
    return folder


def upload_solutions(course, config, wanted):
    """Upload each answer key, locked until its release time. Returns the file names."""
    # A homework with a self-grade shares its key through that assignment instead.
    keys = [w for w in wanted if w.get("solution") and not w.get("_has_self_grade")]
    if not keys:
        return []
    root = config.get("solutions_folder", "Solutions").strip("/")
    for item in keys:
        key = item["solution"]
        release = item["solution_unlock_at"].isoformat()
        # Hidden folder and file: Canvas never lists them to students, and
        # unlock_at keeps the file from opening before the release time.
        path = f"{root}/{Path(item['_source']).stem}"
        folder = find_folder(course, path)
        if folder is None:
            parent, _, name = path.rpartition("/")
            folder = course.create_folder(name, parent_folder_path=parent, hidden=True)
        ok, response = folder.upload(str(key), on_duplicate="overwrite")
        if not ok:
            sys.exit(f"Upload of {key.name} failed: {response}")
        course.get_file(response["id"]).update(
            unlock_at=release, locked=False, hidden=True
        )
        print(f"uploaded  {key.name}  (released {release})")
    return [w["solution"].name for w in keys]


def to_api(fields):
    out = dict(fields)
    out.pop("solution", None)
    out.pop("solution_unlock_at", None)
    for field in TIMES:
        if isinstance(out.get(field), dt.datetime):
            out[field] = out[field].isoformat()
    out["notify_of_update"] = False
    return out


def plan(course, wanted, group_ids, allow_unpublish=False):
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
        diff = changes(item, old, allow_unpublish)
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
    parser.add_argument(
        "--allow-unpublish",
        action="store_true",
        help="let `published: false` unpublish an assignment that is published in Canvas",
    )
    args = parser.parse_args(argv)

    from canvasapi import Canvas

    config, wanted = wanted_assignments(args.config)
    canvas = Canvas(config["url"], get_token(args.keychain_service))
    course = canvas.get_course(config["course_id"])
    group_ids = {g.name: g.id for g in course.get_assignment_groups()}

    print(f"Course: {course.name} ({course.id})")
    print(f"Assignment groups: {', '.join(sorted(group_ids)) or '(none)'}\n")

    missing = [str(p) for w in wanted for p in w["attachments"] if not p.is_file()]
    if missing:
        sys.exit("Attachments not found (build them first):\n  " + "\n  ".join(missing))
    absent = [str(w["solution"]) for w in wanted
              if w.get("solution") and not w["solution"].is_file()]
    if absent:
        sys.exit("Solutions not found (render them first):\n  " + "\n  ".join(absent))
    intro = config.get("attachments_intro", "")

    # Plan once before writing anything, so a bad group name or an ambiguous
    # match stops the run before any upload.
    folder = find_folder(course, config.get("attachments_folder", ""))
    links = file_links(config, folder, wanted)
    steps = plan(course, [with_attachments(w, links, intro) for w in wanted],
                 group_ids, args.allow_unpublish)

    if not args.apply:
        for w in wanted:
            for p in w["attachments"]:
                print(f"would upload {p.name}")
        for w in wanted:
            if w.get("solution"):
                when = w["solution_unlock_at"].isoformat()
                print(f"would upload solution {w['solution'].name}, released {when}")
        report(steps)
        print("\nDry run: nothing was written. Re-run with --apply to write.")
        print("Attachment links show the files now in Canvas; uploading gives them new ids.")
        return

    # Uploading replaces each file with a new one, so re-plan with the new links.
    folder = upload_attachments(course, config, wanted)
    links = file_links(config, folder, wanted)
    steps = plan(course, [with_attachments(w, links, intro) for w in wanted],
                 group_ids, args.allow_unpublish)
    upload_solutions(course, config, wanted)
    report(steps)
    for action, item, diff, old in steps:
        if action == "create":
            course.create_assignment(to_api(diff))
        elif action == "update":
            old.edit(assignment=to_api(diff))
    print("\nApplied.")


if __name__ == "__main__":
    main()
