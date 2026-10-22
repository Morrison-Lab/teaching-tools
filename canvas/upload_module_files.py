# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "canvasapi",
# ]
# ///
"""
Upload files to a Canvas course and add each to a module as an unpublished
file item. Course-agnostic, and meant for a handout or exam sheet that is
built outside Canvas (for example a PDF rendered from a Quarto file).

Run it again and nothing changes unless a file changed: a file is uploaded
over any file of the same name in the Files folder, and a module item is added
only if the module has no item with that title. The folder is created hidden
(reachable by link only), and every new module item is set to unpublished.
Without --apply it is a dry run that prints what it would do and writes
nothing.

Usage:
    uv run upload_module_files.py URL COURSE_ID MODULE_ID FOLDER FILE[=TITLE] ...
    uv run upload_module_files.py ... --apply

    uv run upload_module_files.py https://wwu.instructure.com 1906010 3922395 Exams \\
        midterm1-note-sheet.pdf="Midterm 1 note sheet"

TITLE defaults to the file's name. FOLDER is a Canvas Files folder, relative
to the course's root.

Token: the CANVAS_TOKEN environment variable if set, otherwise the macOS
keychain item named by --keychain-service (default `canvas-token`). The
token is never printed.

Student records: this script calls only the course, folder, file and module
endpoints, never with an include[] parameter, so it reads no roster,
submission or grade.
"""

import argparse
import sys
from pathlib import Path

from sync_assignments import find_folder, get_token


def parse_file_args(specs):
    """Split each FILE[=TITLE] into (path, title); the title defaults to the file name."""
    files = []
    for spec in specs:
        path, _, title = spec.partition("=")
        path = Path(path)
        files.append((path, title or path.name))
    titles = [t for _, t in files]
    dupes = {t for t in titles if titles.count(t) > 1}
    if dupes:
        raise ValueError(f"duplicate titles: {sorted(dupes)}")
    return files


def ensure_folder(course, path):
    """The Files folder at `path`, created hidden if missing."""
    folder = find_folder(course, path)
    if folder is not None:
        return folder
    parent, _, name = path.strip("/").rpartition("/")
    return course.create_folder(name, parent_folder_path=parent, hidden=True)


def upload_and_add(course, module, folder_path, files):
    """Upload each file and add a missing, unpublished module item for it."""
    folder = ensure_folder(course, folder_path)
    existing = {item.title: item for item in module.get_module_items()}
    for path, title in files:
        ok, response = folder.upload(str(path), on_duplicate="overwrite")
        if not ok:
            sys.exit(f"Upload of {path.name} failed: {response}")
        print(f"uploaded  {path.name}")
        if title in existing:
            print(f"unchanged module item {title!r}")
            continue
        item = module.create_module_item(
            module_item={"title": title, "type": "File", "content_id": response["id"]}
        )
        item.edit(module_item={"published": False})
        print(f"added     module item {title!r} (unpublished)")


def report_plan(module, folder_exists, files):
    existing = {item.title for item in module.get_module_items()}
    for path, title in files:
        print(f"would upload {path.name}")
        state = "unchanged" if title in existing else "add, unpublished"
        print(f"          module item {title!r}: {state}")
    if not folder_exists:
        print("          (the Files folder would be created, hidden)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", help="the Canvas site, such as https://wwu.instructure.com")
    parser.add_argument("course_id", type=int)
    parser.add_argument("module_id", type=int)
    parser.add_argument("folder", help="Canvas Files folder, relative to the course root")
    parser.add_argument("files", nargs="+", metavar="FILE[=TITLE]")
    parser.add_argument("--apply", action="store_true", help="write to Canvas")
    parser.add_argument("--keychain-service", default="canvas-token")
    args = parser.parse_args(argv)

    files = parse_file_args(args.files)
    missing = [str(p) for p, _ in files if not p.is_file()]
    if missing:
        sys.exit("Files not found:\n  " + "\n  ".join(missing))

    from canvasapi import Canvas

    canvas = Canvas(args.url, get_token(args.keychain_service))
    course = canvas.get_course(args.course_id)
    module = course.get_module(args.module_id)
    print(f"Course: {course.name} ({course.id}); module: {module.name} ({module.id})\n")

    if not args.apply:
        report_plan(module, find_folder(course, args.folder) is not None, files)
        print("\nDry run: nothing was written. Re-run with --apply to write.")
        return
    upload_and_add(course, module, args.folder, files)
    print("\nApplied.")


if __name__ == "__main__":
    main()
