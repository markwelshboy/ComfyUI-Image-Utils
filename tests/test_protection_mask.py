"""Saved protection mask companion and LC pipe rehydration regressions.

NumPy + Pillow only: ComfyUI, Torch and a GPU are not needed in CI.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_pack():
    name = "image_utils_mask_companion_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    pack = importlib.util.module_from_spec(spec)
    sys.modules[name] = pack
    spec.loader.exec_module(pack)
    return pack


class Tensor:
    """Enough of the Torch IMAGE and MASK APIs to exercise these nodes."""
    def __init__(self, value):
        self.data = np.asarray(value, dtype=np.float32)
        self.shape = self.data.shape

    def __getitem__(self, key):
        return Tensor(self.data[key])

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.data

    def float(self):
        return self

    def sum(self):
        return np.float32(self.data.sum(dtype=np.float32))


class ProtectionMaskTests(unittest.TestCase):
    def setUp(self):
        self.dir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir_obj.cleanup)
        self.root = Path(self.dir_obj.name)
        self.pack = load_pack()
        # Distinct masks: soft values must survive round-trip *exactly*.
        masks = np.zeros((2, 48, 64), dtype=np.float32)
        masks[0, 4:20, 10:30] = np.float32(0.375)
        masks[1, 25:42, 20:49] = np.float32(0.71875)
        self.masks = masks
        self.images = Tensor(np.full((2, 48, 64, 3), 0.43, dtype=np.float32))
        self.folder_paths = SimpleNamespace(
            get_output_directory=lambda: str(self.root),
            get_save_image_path=lambda *args: (
                str(self.root), "batch-%batch_num%", 1, "", "")
        )
        self.json = json.dumps({
            "version": 1, "tags": ["mouth-open"],
            "controls": {"face_detailer": {"denoise": 0.25}},
            "prompts": {"base": "Portrait"},
            "history": [], "origin": {"source_filename": "original.jpg"},
        })

    def save(self, mask=None):
        with mock.patch.dict(sys.modules, {"folder_paths": self.folder_paths}):
            saver = self.pack.ImageUtilsSaveImageWithSidecar()
            return saver.save_images(
                self.images, self.json, protection_mask=mask)

    def test_registration_save_input_and_restore_outputs(self):
        nodes = self.pack.NODE_CLASS_MAPPINGS
        self.assertEqual(len(nodes), 17)
        self.assertIn("protection_mask",
                      nodes["ImageUtilsSaveImageWithSidecar"].INPUT_TYPES()["optional"])
        cls = nodes["ImageUtilsMRLoadProtectionIntoPipe"]
        self.assertFalse(cls.OUTPUT_NODE)
        self.assertEqual(cls.RETURN_TYPES, ("LC_PIPE", "MASK", "BOOLEAN"))
        self.assertEqual(cls.RETURN_NAMES, ("pipe", "protection_mask", "found"))
        self.assertEqual(cls.INPUT_TYPES()["required"]["image"][0], "IMAGE")
        self.assertEqual(cls.INPUT_TYPES()["required"]["image_path"][0], "STRING")
        self.assertEqual(cls.INPUT_TYPES()["optional"]["pipe"][0], "LC_PIPE")

    def test_roundtrip_saves_exact_mask_each_frame_and_json_provenance(self):
        result = self.save(Tensor(self.masks))
        self.assertEqual(len(result["ui"]["images"]), 2)
        for i in (0, 1):
            filename = result["ui"]["images"][i]["filename"]
            path = self.root / filename
            sidecar = path.with_suffix(".sidecar")
            companion = path.with_suffix(".protection_mask")
            self.assertTrue(path.exists())
            self.assertTrue(sidecar.exists())
            self.assertTrue(companion.exists())
            self.assertEqual(companion.read_bytes()[:4], b"PK\x03\x04")
            from_name = self.pack.ImageUtilsSidecarLoader().load(str(path))
            self.assertTrue(from_name[1])
            doc = json.loads(from_name[0])
            self.assertEqual(doc["controls"]["face_detailer"]["denoise"], 0.25)
            self.assertEqual(doc["origin"]["source_filename"], "original.jpg")
            self.assertEqual(doc["history"][-1]["protection_mask_file"], companion.name)
            with Image.open(path) as saved:
                embedded = json.loads(saved.info["image_sidecar"])
            self.assertEqual(doc, embedded)
            from_pack = __import__("image_utils_mask_companion_test.protection_mask", fromlist=["read_protection_file"])
            loaded = from_pack.read_protection_file(path, expected_shape=(48, 64))
            np.testing.assert_array_equal(loaded, self.masks[i])

    def test_without_mask_saves_no_companion(self):
        result = self.save()
        for entry in result["ui"]["images"]:
            path = self.root / entry["filename"]
            self.assertFalse(path.with_suffix(".protection_mask").exists())
            doc = json.loads(path.with_suffix(".sidecar").read_text())
            self.assertNotIn("protection_mask_file", doc["history"][-1])

    def test_validates_entire_batch_before_writing_any_output(self):
        for raw in (
            np.ones((1, 48, 64), dtype=np.float32),  # won't broadcast silently
            np.ones((2, 32, 64), dtype=np.float32),
            np.full((2, 48, 64), np.nan, dtype=np.float32),
            np.full((2, 48, 64), 1.1, dtype=np.float32),
        ):
            with self.subTest(shape=raw.shape), self.assertRaises(ValueError):
                self.save(Tensor(raw))
            self.assertEqual(list(self.root.iterdir()), [])

    def test_no_overwrite_and_all_companions_cleaned_if_mask_commit_fails(self):
        # Make os.replace fail on the *third* file (mask) to test rollback.
        actual_replace = os.replace
        calls = []
        def fail_mask(src, dst):
            calls.append(Path(dst))
            if str(dst).endswith(".protection_mask"):
                raise OSError("forced mask failure")
            return actual_replace(src, dst)
        with mock.patch("os.replace", side_effect=fail_mask):
            with self.assertRaisesRegex(OSError, "forced mask failure"):
                self.save(Tensor(self.masks))
        self.assertEqual(list(self.root.iterdir()), [],
                         "No orphan PNG, JSON or mask is allowed after a failure")

    def test_restore_with_optional_existing_pipe_retags_for_loaded_png(self):
        produced = self.save(Tensor(self.masks))
        png = self.root / produced["ui"]["images"][0]["filename"]
        with Image.open(png) as saved:
            pixels = np.array(saved.convert("RGB"), dtype=np.float32) / 255.0
        restored_image = Tensor(pixels[None, ...])
        prior_model = object()
        old_pipe = {
            "_type": "LC_PIPE", "image": restored_image,
            "model_1": prior_model, "seed": 999,
            "lc_found": {"tag": "stale", "hits": {"face": "stale"}},
        }
        torch_mock = SimpleNamespace(
            from_numpy=lambda arr: Tensor(arr),
            zeros=lambda shape, dtype: Tensor(np.zeros(shape, dtype=np.float32)),
            float32=np.float32,
        )
        with mock.patch.dict(sys.modules, {"torch": torch_mock}):
            pipe, mask, found = self.pack.MRLoadProtectionIntoPipe().load(
                image_path=str(png), image=restored_image, pipe=old_pipe)
        self.assertTrue(found)
        self.assertEqual(pipe["_type"], "LC_PIPE")
        self.assertIs(pipe["image"], restored_image)
        self.assertIs(pipe["model_1"], prior_model)
        self.assertEqual(pipe["seed"], 999)
        self.assertNotIn("lc_found", pipe)
        self.assertIsNot(pipe, old_pipe)
        self.assertNotIn("lc_protect", old_pipe)
        self.assertIs(pipe["lc_protect"]["mask"], mask)
        np.testing.assert_array_equal(mask.numpy()[0], self.masks[0])
        from_name = self.pack.MRPipeImageReplaceProtect.__module__
        module = sys.modules[from_name]
        current_tag = module._lc_image_tag(restored_image)
        self.assertEqual(pipe["lc_protect"]["tag"], current_tag)
        # Even though image-save quantized the pixels, LoneCat can now retrieve
        # the rehydrated mask using its *new* fingerprint.
        self.assertIsNotNone(pipe["lc_protect"]["mask"] if
                             pipe["lc_protect"]["tag"] == current_tag else None)

    def test_restore_can_build_minimal_pipe_without_existing_pipe(self):
        produced = self.save(Tensor(self.masks))
        png = self.root / produced["ui"]["images"][0]["filename"]
        image = Tensor(np.zeros((1, 48, 64, 3), dtype=np.float32))
        with mock.patch.dict(sys.modules, {"torch": SimpleNamespace(
            from_numpy=lambda arr: Tensor(arr), zeros=lambda shape, dtype: Tensor(np.zeros(shape)),
            float32=np.float32)}):
            pipe, mask, found = self.pack.MRLoadProtectionIntoPipe().load(str(png), image)
        self.assertTrue(found)
        self.assertEqual(set(pipe), {"_type", "image", "lc_protect"})
        np.testing.assert_array_equal(mask.numpy()[0], self.masks[0])

    def test_missing_protection_error_or_explicit_empty(self):
        fake_image = self.root / "no companion.png"
        image = Tensor(np.zeros((1, 48, 64, 3), dtype=np.float32))
        node = self.pack.MRLoadProtectionIntoPipe()
        with mock.patch.dict(sys.modules, {"torch": SimpleNamespace(
            from_numpy=lambda arr: Tensor(arr), zeros=lambda shape, dtype: Tensor(np.zeros(shape)),
            float32=np.float32)}):
            with self.assertRaisesRegex(FileNotFoundError, "No protection mask"):
                node.load(str(fake_image), image)
            old = {"_type": "LC_PIPE", "image": image,
                   "lc_protect": {"mask": "old", "tag": "stale"}}
            pipe, mask, exists = node.load(str(fake_image), image,
                                           missing_policy="empty", pipe=old)
        self.assertFalse(exists)
        self.assertNotIn("lc_protect", pipe)
        np.testing.assert_array_equal(mask.numpy(), np.zeros((1, 48, 64)))
        self.assertIn("lc_protect", old)

    def test_incorrect_image_geometry_or_batch_rejected(self):
        produced = self.save(Tensor(self.masks))
        png = self.root / produced["ui"]["images"][0]["filename"]
        node = self.pack.MRLoadProtectionIntoPipe()
        with mock.patch.dict(sys.modules, {"torch": SimpleNamespace(
            from_numpy=lambda arr: Tensor(arr), zeros=lambda shape, dtype: Tensor(np.zeros(shape)),
            float32=np.float32)}):
            with self.assertRaisesRegex(ValueError, "one at a time"):
                node.load(str(png), Tensor(np.zeros((2, 48, 64, 3), dtype=np.float32)))
            with self.assertRaisesRegex(ValueError, "does not match image"):
                node.load(str(png), Tensor(np.zeros((1, 32, 64, 3), dtype=np.float32)))

    def test_prefer_full_image_filename_companion_when_present(self):
        name = self.root / "similar.jpg"
        name.write_bytes(b"same")
        module = __import__("image_utils_mask_companion_test.protection_mask",
                            fromlist=["protection_for_image", "write_protection_file"])
        module.write_protection_file(name.with_suffix(".protection_mask"), self.masks[0])
        full = Path(str(name) + ".protection_mask")
        module.write_protection_file(full, self.masks[1])
        self.assertEqual(module.protection_for_image(name), full)
        np.testing.assert_array_equal(module.read_protection_file(name), self.masks[1])

    def test_corrupt_archive_and_file_change_signature(self):
        module = __import__("image_utils_mask_companion_test.protection_mask",
                            fromlist=["protection_signature"])
        name = self.root / "corrupt.png"
        missing_sig = module.protection_signature(name)
        companion = name.with_suffix(".protection_mask")
        companion.write_bytes(b"not a zip")
        self.assertNotEqual(module.protection_signature(name), missing_sig)
        with self.assertRaises(ValueError):
            module.read_protection_file(name)


if __name__ == "__main__":
    unittest.main()
