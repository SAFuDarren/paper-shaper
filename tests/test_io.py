"""Bounded-memory and text compatibility checks on synthetic files."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
try:
    import tracemalloc
except ImportError:
    tracemalloc = None
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/workflow_state.py"
SPEC = importlib.util.spec_from_file_location("io_checks", SOURCE)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class SourceIO(unittest.TestCase):
    @unittest.skipUnless(tracemalloc is not None, "Python allocation tracing is unavailable on this interpreter")
    def test_hash_of_a_large_file_has_bounded_python_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.bin"
            chunk = b"synthetic source\n" * 4096
            expected = hashlib.sha256()
            with source.open("wb") as stream:
                for _ in range(128):
                    stream.write(chunk)
                    expected.update(chunk)
            tracemalloc.start()
            try:
                result = core.digest(source)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertEqual(result, expected.hexdigest())
            self.assertLess(peak, 4 * 1024 * 1024)

    @unittest.skipUnless(tracemalloc is not None, "Python allocation tracing is unavailable on this interpreter")
    def test_small_excerpt_from_a_large_multiline_file_has_bounded_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.txt"
            line = "synthetic line " + "x" * 1000 + "\n"
            with source.open("w", encoding="utf-8") as stream:
                for _ in range(8192):
                    stream.write(line)
            tracemalloc.start()
            try:
                result = core.excerpt(source, 2, 3)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertEqual(result, "2: " + line.rstrip() + "\n3: " + line.rstrip())
            self.assertLess(peak, 1024 * 1024)

    def test_bom_and_windows_newlines_preserve_line_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_bytes(b"\xef\xbb\xbf" + "第一行\r\n第二行\r\n".encode("utf-8"))
            self.assertEqual(core.excerpt(source, 1, 2), "1: 第一行\n2: 第二行")
            with self.assertRaises(ValueError):
                core.excerpt(source, 1, 3)


if __name__ == "__main__":
    unittest.main()
