"""MR LC pipe IMAGE replacement tests: validates protection across SEGS roundtrip.

Uses a small NumPy-backed stand-in for Torch IMAGE to keep CI GPU-free.
The node computes LoneCat's exact sampled-float fingerprint.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_pack():
    name = "image_utils_mr_pipe_replace_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    pack = importlib.util.module_from_spec(spec)
    sys.modules[name] = pack
    spec.loader.exec_module(pack)
    return pack


class ImageTensor:
    """Small IMAGE tensor shim implementing LoneCat's sampled .float().sum()."""
    def __init__(self, pixels):
        self.pixels = np.asarray(pixels, dtype=np.float32)
        self.shape = self.pixels.shape

    def __getitem__(self, item):
        return ImageTensor(self.pixels[item])

    def float(self):
        return self

    def sum(self):
        return np.float32(self.pixels.sum(dtype=np.float32))


def tag(image):
    return (tuple(image.shape),
            round(float(image[:, ::37, ::37, :3].float().sum()), 3))


class PipeImageReplacementTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack()
        self.node = self.pack.MRPipeImageReplaceProtect()
        self.before = ImageTensor(np.zeros((2, 60, 75, 3), dtype=np.float32))
        self.after = ImageTensor(np.ones((2, 60, 75, 3), dtype=np.float32) * 0.4)
        self.protect = np.zeros((2, 60, 75), dtype=np.float32)
        self.protect[0, 10:20, 10:20] = 0.7
        self.protect[1, 25:40, 30:50] = 1.0
        self.original = {
            "_type": "LC_PIPE",
            "image": self.before,
            "model_1": object(),
            "positive": object(),
            "seed": 1234,
            "lc_protect": {"mask": self.protect, "tag": tag(self.before), "source": "three detailers"},
            "lc_found": {"tag": tag(self.before), "hits": {"face": "cached"}},
        }

    def test_registered_node_has_exact_two_inputs_and_one_pipe_output(self):
        cls = self.pack.NODE_CLASS_MAPPINGS["ImageUtilsMRPipeImageReplaceProtect"]
        self.assertIs(cls, self.pack.MRPipeImageReplaceProtect)
        self.assertEqual(cls.RETURN_TYPES, ("LC_PIPE",))
        self.assertEqual(cls.RETURN_NAMES, ("pipe",))
        self.assertEqual(cls.FUNCTION, "replace")
        self.assertFalse(cls.OUTPUT_NODE)
        self.assertEqual(
            {k: v[0] for k, v in cls.INPUT_TYPES()["required"].items()},
            {"pipe": "LC_PIPE", "image": "IMAGE"},
        )
        self.assertNotIn("optional", cls.INPUT_TYPES())
        self.assertEqual(
            self.pack.NODE_DISPLAY_NAME_MAPPINGS["ImageUtilsMRPipeImageReplaceProtect"],
            "MR Pipe Image Replace (Preserve Protection)",
        )

    def test_retains_previous_protection_exactly_and_retags_for_new_image(self):
        replaced, = self.node.replace(self.original, self.after)
        self.assertIsNot(replaced, self.original)
        self.assertIs(replaced["image"], self.after)
        self.assertIs(replaced["lc_protect"]["mask"], self.protect)
        np.testing.assert_array_equal(replaced["lc_protect"]["mask"], self.protect)
        self.assertEqual(replaced["lc_protect"]["tag"], tag(self.after))
        self.assertEqual(replaced["lc_protect"]["source"], "three detailers")
        self.assertEqual(replaced["seed"], 1234)
        self.assertIs(replaced["model_1"], self.original["model_1"])
        self.assertIs(replaced["positive"], self.original["positive"])
        self.assertNotIn("lc_found", replaced)
        # Strictly no changes to original pipe, mask or protection fingerprint.
        self.assertIs(self.original["image"], self.before)
        self.assertEqual(self.original["lc_protect"]["tag"], tag(self.before))
        self.assertIn("lc_found", self.original)
        self.assertIsNot(replaced["lc_protect"], self.original["lc_protect"])
        # A downstream LoneCat detailer now reads the existing protection and
        # merges its new mask with it, not just the final detailer's region.
        retrieved = (replaced["lc_protect"]["mask"] if
                     replaced["lc_protect"]["tag"] == tag(replaced["image"]) else None)
        self.assertIs(retrieved, self.protect)
        final_mask = np.zeros_like(self.protect)
        final_mask[:, 2:9, 3:12] = 1
        merged = np.maximum(retrieved, final_mask)
        self.assertEqual(merged[0, 12, 12], 0.7)
        self.assertEqual(merged[0, 5, 5], 1.0)
        self.assertEqual(merged[1, 30, 40], 1.0)

    def test_empty_protection_keeps_other_pipe_fields_and_discards_old_hits(self):
        old = {k: v for k, v in self.original.items() if k != "lc_protect"}
        replaced, = self.node.replace(old, self.after)
        self.assertNotIn("lc_protect", replaced)
        self.assertNotIn("lc_found", replaced)
        self.assertIs(replaced["image"], self.after)
        self.assertEqual(replaced["seed"], 1234)

    def test_identity_input_image_still_retains_and_drops_detection_cache(self):
        replaced, = self.node.replace(self.original, self.before)
        self.assertIs(replaced["image"], self.before)
        self.assertIs(replaced["lc_protect"]["mask"], self.protect)
        self.assertEqual(replaced["lc_protect"]["tag"], tag(self.before))
        self.assertNotIn("lc_found", replaced)

    def test_rejects_missing_or_invalid_lc_pipe(self):
        for invalid in (None, {}, {"_type": "WRONG", "image": self.before}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.node.replace(invalid, self.after)

    def test_rejects_geometry_batch_or_channel_changes(self):
        for shape in ((1, 60, 75, 3), (2, 61, 75, 3),
                      (2, 60, 76, 3), (2, 60, 75, 4)):
            with self.subTest(shape=shape), self.assertRaisesRegex(ValueError, "shape"):
                self.node.replace(self.original, ImageTensor(np.zeros(shape, dtype=np.float32)))

    def test_refuses_to_retag_stale_protection(self):
        stale = dict(self.original)
        stale["lc_protect"] = {
            "mask": self.protect,
            "tag": (tuple(self.before.shape), 123.0),
        }
        with self.assertRaisesRegex(ValueError, "already stale"):
            self.node.replace(stale, self.after)
        self.assertEqual(stale["lc_protect"]["tag"][1], 123.0)

    def test_rejects_mismatched_protection_size(self):
        bad = dict(self.original)
        bad["lc_protect"] = {
            "mask": np.zeros((2, 30, 75), dtype=np.float32),
            "tag": tag(self.before),
        }
        with self.assertRaisesRegex(ValueError, "mask shape"):
            self.node.replace(bad, self.after)

    def test_rejects_invalid_protection_payload(self):
        for broken in ("bad", {"mask": None}):
            with self.subTest(broken=broken), self.assertRaisesRegex(ValueError, "invalid"):
                self.node.replace({**self.original, "lc_protect": broken}, self.after)

    def test_sampled_checksum_matches_lonecat_exactly(self):
        original = np.zeros((1, 74, 76, 3), dtype=np.float32)
        original[0, 37, 74, 0] = 0.123456
        original[0, 0, 0, 2] = 0.234567
        original[0, 15, 15, 0] = 1.0  # deliberately not sampled
        image = ImageTensor(original)
        from_name = self.pack.MRPipeImageReplaceProtect
        # Test through the node: it only accepts the exact LoneCat fingerprint.
        pipe = {
            "_type": "LC_PIPE", "image": image,
            "lc_protect": {
                "tag": tag(image),
                "mask": np.zeros((1, 74, 76), dtype=np.float32),
            },
        }
        result, = from_name().replace(pipe, image)
        self.assertEqual(result["lc_protect"]["tag"], tag(image))


if __name__ == "__main__":
    unittest.main()
