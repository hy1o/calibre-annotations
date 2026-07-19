import sys
import unittest
from unittest import mock

from compat_import import DynamicImportError, load_source_module


class DynamicImportTests(unittest.TestCase):
    def test_load_source_module_inserts_and_executes_module(self):
        with self.subTest("dynamic source import"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tdir:
                source = Path(tdir) / "dynamic_reader.py"
                source.write_text("VALUE = 42\n", encoding="utf-8")

                module = load_source_module("dynamic_reader_test", str(source))

                self.assertEqual(module.VALUE, 42)
                self.assertIs(sys.modules["dynamic_reader_test"], module)

    def test_load_source_module_raises_clear_error_for_missing_loader(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tdir:
            source = Path(tdir) / "dynamic_reader.py"
            source.write_text("VALUE = 42\n", encoding="utf-8")

            with mock.patch("importlib.util.spec_from_file_location", return_value=None):
                with self.assertRaisesRegex(DynamicImportError, "Unable to create an import spec"):
                    load_source_module("dynamic_reader_bad", str(source))


if __name__ == "__main__":
    unittest.main()
