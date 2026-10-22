"""Self-test for upload_module_files.py against a fake course; no network.

Run: python3 canvas/tests/test_upload_module_files.py
"""

import sys
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upload_module_files as umf  # noqa: E402


class FakeItem:
    def __init__(self, title):
        self.title = title
        self.edits = []

    def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeFolder:
    def __init__(self):
        self.uploads = []

    def upload(self, path, **kwargs):
        assert kwargs == {"on_duplicate": "overwrite"}, kwargs
        self.uploads.append(path)
        return True, {"id": 100 + len(self.uploads)}


class FakeModule:
    def __init__(self, titles):
        self.items = [FakeItem(t) for t in titles]
        self.created = []

    def get_module_items(self, **kwargs):
        # The script must never ask for extra (possibly student) data.
        assert not kwargs, kwargs
        return self.items

    def create_module_item(self, module_item):
        item = FakeItem(module_item["title"])
        self.created.append(module_item)
        self.items.append(item)
        return item


class FakeCourse:
    def __init__(self, folder):
        self.folder = folder
        self.created_folders = []

    def get_folders(self):
        if self.folder is None:
            return []
        return [SimpleNamespace(full_name="course files/Exams", upload=self.folder.upload)]

    def create_folder(self, name, parent_folder_path, hidden):
        assert hidden is True
        self.created_folders.append((name, parent_folder_path))
        self.folder = FakeFolder()
        return self.folder


class UploadTest(unittest.TestCase):
    def run_upload(self, course, module, files):
        with redirect_stdout(StringIO()):
            umf.upload_and_add(course, module, "Exams", files)

    def test_title_defaults_to_file_name(self):
        files = umf.parse_file_args(["a.pdf=Note sheet", "b.pdf"])
        self.assertEqual(files, [(Path("a.pdf"), "Note sheet"), (Path("b.pdf"), "b.pdf")])

    def test_duplicate_titles_refused(self):
        with self.assertRaises(ValueError):
            umf.parse_file_args(["a.pdf=X", "b.pdf=X"])

    def test_creates_hidden_folder_and_unpublished_items(self):
        course, module = FakeCourse(None), FakeModule([])
        self.run_upload(course, module, [(Path("a.pdf"), "Note sheet")])
        self.assertEqual(course.created_folders, [("Exams", "")])
        self.assertEqual(
            module.created,
            [{"title": "Note sheet", "type": "File", "content_id": 101}],
        )
        self.assertEqual(module.items[0].edits, [{"module_item": {"published": False}}])

    def test_second_run_adds_no_duplicate_item(self):
        course, module = FakeCourse(FakeFolder()), FakeModule(["Note sheet"])
        self.run_upload(course, module, [(Path("a.pdf"), "Note sheet")])
        self.assertEqual(module.created, [])
        self.assertEqual(len(module.items), 1)
        self.assertEqual(course.folder.uploads, ["a.pdf"])


if __name__ == "__main__":
    unittest.main()
