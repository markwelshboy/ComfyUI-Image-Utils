"""API-controlled loader pathname and socket compatibility, without GPU/ComfyUI."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mr_api_input_test", ROOT / "api_input.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ImageCompareAPIInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "input"
        self.input.mkdir()
        self.picture = self.input / "image-compare" / ("f" * 32) / "portrait.png"
        self.picture.parent.mkdir(parents=True)
        self.picture.write_bytes(b"test")

    def test_stateless_input_matches_sequential_loader_sockets(self):
        node = mod.MRImageCompareInput
        self.assertEqual(node.RETURN_TYPES,
                         ("IMAGE", "MASK", "STRING", "INT", "INT", "STRING"))
        self.assertEqual(node.RETURN_NAMES[-1], "file_path")
        self.assertEqual(node.resolve(str(self.picture.relative_to(self.input)), self.input),
                         self.picture)

    def test_reject_paths_outside_input_directory(self):
        outside = self.root / "other.png"
        outside.write_bytes(b"test")
        node = mod.MRImageCompareInput
        for value in (str(outside), "../../other.png", "../other.png",
                      "", "a\\b.png"):
            with self.assertRaises(ValueError, msg=value):
                node.resolve(value, self.input)
        alias = self.input / "escape.png"
        alias.symlink_to(outside)
        with self.assertRaises(ValueError):
            node.resolve(alias.name, self.input)

    def test_reject_unsupported_extension(self):
        file = self.input / "data.sidecar"
        file.write_text("{}")
        with self.assertRaises(ValueError):
            mod.MRImageCompareInput.resolve(file.name, self.input)


if __name__ == "__main__":
    unittest.main()
