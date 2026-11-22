"""API-controlled loader pathname and socket compatibility, without GPU/ComfyUI."""
import importlib.util
import json
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

    def test_output_manifest_recovers_exact_lineage_without_directory_escape(self):
        run = "a" * 32
        output = self.root / "output" / "image-compare" / run
        output.mkdir(parents=True)
        one = "refined_0001"
        (output / (one + ".png")).write_bytes(b"png")
        ids = {"asset_id": "b" * 32, "variant_id": None,
               "parent_artifact_id": "c" * 32, "artifact_id": "d" * 32}
        (output / (one + ".sidecar")).write_text(json.dumps({"lineage": ids}))
        # Orphaned sidecars or partial outputs must not be adopted.
        (output / "orphan.sidecar").write_text(json.dumps({"lineage": ids}))
        (output / "temporary.png").write_bytes(b"png")
        (output / ".temp.sidecar").write_text("{invalid")
        manifest = mod.image_compare_output_manifest(self.root / "output", run)
        self.assertEqual(len(manifest["entries"]), 1)
        entry = manifest["entries"][0]
        self.assertEqual(entry["filename"], one + ".png")
        self.assertEqual(entry["parent_artifact_id"], ids["parent_artifact_id"])
        self.assertEqual(entry["asset_id"], ids["asset_id"])
        self.assertEqual(entry["subfolder"], "image-compare/" + run)
        self.assertFalse(manifest["truncated"])
        for bad in ("../x", "/etc/passwd", "x" * 31):
            with self.assertRaises(ValueError):
                mod.image_compare_output_manifest(self.root / "output", bad)
        self.assertEqual(mod.image_compare_output_manifest(
            self.root / "output", "f" * 32)["entries"], [])

    def test_output_manifest_refuses_symlink_escape(self):
        run = "f" * 32
        output_root = self.root / "output"
        output_root.mkdir()
        external = self.root / "external"
        external.mkdir()
        (output_root / "image-compare").mkdir()
        (output_root / "image-compare" / run).symlink_to(external)
        with self.assertRaises(ValueError):
            mod.image_compare_output_manifest(output_root, run)



if __name__ == "__main__":
    unittest.main()
