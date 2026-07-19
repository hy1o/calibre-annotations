import os
import tempfile
import unittest
from pathlib import Path

from device_compat import (
    DeviceCapabilityError,
    DeviceDisconnectedError,
    FilesystemDeviceAdapter,
    MTPDeviceAdapter,
    device_adapter_for,
)


class FakeUSBMSDevice:
    EBOOK_DIR_MAIN = "documents"
    EBOOK_DIR_CARD_A = "documents"
    EBOOK_DIR_CARD_B = "documents"

    def __init__(self, root):
        self._main_prefix = str(root)
        self._card_a_prefix = None
        self._card_b_prefix = None

    def create_annotations_path(self, mi, device_path=None):
        return os.path.splitext(device_path)[0] + ".bookmark"

    def metadata_from_path(self, path):
        return {"path": path}


class FakeMTPEntry:
    def __init__(self, name, object_id, parent=None, is_folder=False, content=b""):
        self.name = name
        self.object_id = object_id
        self.parent = parent
        self.is_folder = is_folder
        self.content = content
        self.files = []
        self.folders = []
        self.mtp_id_path = "mtp:::{0}:::{1}".format(object_id, "/".join(self.full_path))
        if parent is not None:
            target = parent.folders if is_folder else parent.files
            target.append(self)

    @property
    def full_path(self):
        if self.parent is None:
            return (self.name,)
        return self.parent.full_path + (self.name,)

    def find_path(self, parts):
        node = self
        for part in parts:
            lower = part.lower()
            children = node.folders + node.files
            node = next((child for child in children if child.name.lower() == lower), None)
            if node is None:
                return None
        return node


class FakeMTPFilesystemCache:
    def __init__(self, storage):
        self.entries = [storage]

    def resolve_mtp_id_path(self, path):
        object_id = int(path.split(":::", 2)[1])
        stack = list(self.entries)
        while stack:
            entry = stack.pop()
            if entry.object_id == object_id:
                return entry
            stack.extend(entry.folders)
            stack.extend(entry.files)
        raise ValueError("No object found")


class FakeMTPDevice:
    def __init__(self, fail_get_file=False):
        storage = FakeMTPEntry("Internal Storage", 1, is_folder=True)
        documents = FakeMTPEntry("documents", 2, parent=storage, is_folder=True)
        self.book = FakeMTPEntry("Café Notes.azw3", 3, parent=documents, content=b"book")
        self.clippings = FakeMTPEntry("My Clippings.txt", 4, parent=documents, content="Café\n".encode("utf-8"))
        self.filesystem_cache = FakeMTPFilesystemCache(storage)
        self.fail_get_file = fail_get_file

    def get_file(self, mtp_id_path, outfile):
        if self.fail_get_file:
            raise OSError("device disconnected")
        entry = self.filesystem_cache.resolve_mtp_id_path(mtp_id_path)
        outfile.write(entry.content)

    def read_file_metadata(self, entry):
        return {"name": entry.name}


class DeviceCompatTests(unittest.TestCase):
    def test_usbms_path_generation_and_resolution(self):
        with tempfile.TemporaryDirectory() as tdir:
            root = Path(tdir)
            book = root / "documents" / "Book.azw3"
            book.parent.mkdir()
            book.write_bytes(b"book")

            adapter = FilesystemDeviceAdapter(FakeUSBMSDevice(root))
            annotation_path = adapter.create_annotations_path(None, device_path=str(book))

            self.assertTrue(annotation_path.endswith("Book.bookmark"))
            self.assertEqual(
                adapter.resolve_book_path(annotation_path, ["azw3"], [str(book.parent)], ["azw3"]),
                str(book),
            )

    def test_mtp_path_generation_without_create_annotations_path(self):
        device = FakeMTPDevice()
        adapter = MTPDeviceAdapter(device)

        annotation_path = adapter.create_annotations_path(None, device.book.mtp_id_path)

        self.assertEqual(annotation_path, "Internal Storage/documents/Café Notes.bookmark")

    def test_kindle_installed_book_path_mapping_for_mtp(self):
        device = FakeMTPDevice()
        adapter = MTPDeviceAdapter(device)

        resolved = adapter.resolve_book_path(
            "Internal Storage/documents/Café Notes.bookmark",
            ["azw3"],
            adapter.get_storage_paths(),
            ["azw3", "mobi", "pdf"],
        )

        self.assertEqual(resolved, "Internal Storage/documents/Café Notes.azw3")

    def test_annotation_file_retrieval_through_mocked_mtp_device(self):
        adapter = MTPDeviceAdapter(FakeMTPDevice())

        with adapter.materialize_file("Internal Storage/documents/My Clippings.txt") as path:
            with open(path, "rb") as f:
                self.assertEqual(f.read(), "Café\n".encode("utf-8"))

    def test_mtp_temp_files_are_cleaned_up(self):
        adapter = MTPDeviceAdapter(FakeMTPDevice())

        with adapter.materialize_file("Internal Storage/documents/My Clippings.txt") as path:
            self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path))

    def test_missing_mtp_capabilities_raise_useful_error(self):
        with self.assertRaisesRegex(DeviceCapabilityError, "filesystem_cache/get_file"):
            MTPDeviceAdapter(object())

    def test_disconnected_mtp_device_raises_useful_error(self):
        adapter = MTPDeviceAdapter(FakeMTPDevice(fail_get_file=True))

        with self.assertRaisesRegex(DeviceDisconnectedError, "Unable to retrieve"):
            adapter.materialize_file("Internal Storage/documents/My Clippings.txt")

    def test_unicode_paths_and_filenames_are_preserved(self):
        adapter = MTPDeviceAdapter(FakeMTPDevice())

        self.assertTrue(adapter.exists("Internal Storage/documents/Café Notes.azw3"))
        self.assertEqual(adapter.metadata_from_path("Internal Storage/documents/Café Notes.azw3"), {"name": "Café Notes.azw3"})

    def test_device_adapter_for_selects_mtp_without_create_annotations_path(self):
        device = FakeMTPDevice()

        self.assertIsInstance(device_adapter_for(device), MTPDeviceAdapter)
        self.assertFalse(hasattr(device, "create_annotations_path"))


if __name__ == "__main__":
    unittest.main()
