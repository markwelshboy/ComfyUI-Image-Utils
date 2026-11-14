"""No-GPU tests for sidecar AnyPaint masks and their ComfyUI node contract."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def package():
    name = "image_utils_polygon_tests"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeTorchArray:
    def __init__(self, pixels):
        self.pixels = pixels
        self.shape = pixels.shape
    def unsqueeze(self, axis):
        return FakeTorchArray(np.expand_dims(self.pixels, axis))
    def repeat(self, count, height, width):
        return FakeTorchArray(np.tile(self.pixels, (count, height, width)))


class PolygonTests(unittest.TestCase):
    def setUp(self):
        self.pack = package()
        self.doc = {
            "version": 1,
            "masks": {"anypaint": {
                "enabled": True, "reference_size": [100, 100],
                "prompt": "Remove misplaced tattoo and restore clear skin.",
                "regions": [
                    {"operation": "add", "points": [
                        [0.1, 0.1], [0.8, 0.1], [0.8, 0.8], [0.1, 0.8]]},
                    {"operation": "subtract", "points": [
                        [0.3, 0.3], [0.6, 0.3], [0.6, 0.6], [0.3, 0.6]]},
                ],
            }}
        }

    def test_contract_and_rasterization(self):
        cls = self.pack.NODE_CLASS_MAPPINGS["ImageUtilsPolygonMaskExtractor"]
        self.assertEqual(cls.RETURN_TYPES, ("MASK", "BOOLEAN", "STRING"))
        self.assertEqual(cls.RETURN_NAMES, ("mask", "mask_present", "prompt"))
        self.assertEqual({k: t[0] for k, t in cls.INPUT_TYPES()["required"].items()},
                         {"image": "IMAGE", "sidecar_json": "STRING", "mask_name": "STRING"})
        fake_torch = types.SimpleNamespace(from_numpy=lambda x: FakeTorchArray(x))
        with mock.patch.dict(sys.modules, {"torch": fake_torch}):
            m, present, prompt = cls().extract(
                types.SimpleNamespace(shape=(2, 100, 100, 3)),
                json.dumps(self.doc), "anypaint")
        self.assertTrue(present)
        self.assertEqual(prompt, "Remove misplaced tattoo and restore clear skin.")
        self.assertEqual(m.shape, (2, 100, 100))
        self.assertEqual(float(m.pixels[0, 15, 15]), 1.0)
        self.assertEqual(float(m.pixels[0, 50, 50]), 0.0)
        self.assertEqual(float(m.pixels[1, 95, 95]), 0.0)
        np.testing.assert_array_equal(m.pixels[0], m.pixels[1])

    def test_no_mask_or_disabled_mask_has_black_mask_false_and_blank_prompt(self):
        fake_torch = types.SimpleNamespace(from_numpy=lambda x: FakeTorchArray(x))
        cls = self.pack.ImageUtilsPolygonMaskExtractor
        with mock.patch.dict(sys.modules, {"torch": fake_torch}):
            for document in ({}, {"masks": {"anypaint": {
                **self.doc["masks"]["anypaint"], "enabled": False}}}):
                with self.subTest(document=document):
                    m, present, prompt = cls().extract(
                        types.SimpleNamespace(shape=(1, 100, 100, 3)),
                        json.dumps(document))
                    self.assertFalse(present)
                    self.assertEqual(prompt, "")
                    self.assertFalse(m.pixels.any())

    def test_scale_preserves_relative_geometry(self):
        from image_utils_polygon_tests.polygon_mask import make_polygon_image
        img, present, _ = make_polygon_image(self.doc, "anypaint", 200, 200)
        self.assertTrue(present)
        self.assertEqual(img.getpixel((30, 30)), 255)
        self.assertEqual(img.getpixel((100, 100)), 0)
        self.assertEqual(img.getpixel((190, 190)), 0)

    def test_reject_aspect_ratio_changes(self):
        from image_utils_polygon_tests.polygon_mask import make_polygon_image
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            make_polygon_image(self.doc, "anypaint", 120, 200)

    def test_reject_bad_json_and_invalid_polygon(self):
        from image_utils_polygon_tests.polygon_mask import make_polygon_image
        with self.assertRaisesRegex(ValueError, "Invalid JSON"):
            make_polygon_image("{", "anypaint", 100, 100)
        broken = json.loads(json.dumps(self.doc))
        broken["masks"]["anypaint"]["regions"][0]["points"][0] = [-0.01, 0.2]
        with self.assertRaisesRegex(ValueError, "normalized"):
            make_polygon_image(broken, "anypaint", 100, 100)
        broken["masks"]["anypaint"]["regions"][0]["points"][0] = [0, 0]
        broken["masks"]["anypaint"]["regions"][0]["operation"] = "unknown"
        with self.assertRaisesRegex(ValueError, "add or subtract"):
            make_polygon_image(broken, "anypaint", 100, 100)


if __name__ == "__main__":
    unittest.main()
