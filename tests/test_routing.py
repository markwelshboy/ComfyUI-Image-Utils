"""Routing and inline preview regression tests (no live ComfyUI required)."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_nodes():
    name = "image_utils_routing_test_package"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    pack = importlib.util.module_from_spec(spec)
    sys.modules[name] = pack
    spec.loader.exec_module(pack)
    return pack


class FakeTensor:
    def __init__(self, array):
        self.array = array
    def detach(self):
        return self
    def cpu(self):
        return self
    def numpy(self):
        return self.array


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_nodes()
        self.routing = importlib.import_module(
            "image_utils_routing_test_package.routing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_node_registration_and_types(self):
        registry = self.pack.NODE_CLASS_MAPPINGS
        self.assertEqual(len(registry), 17)
        for name in ("ImageUtilsLazyImageBypass", "ImageUtilsTagPromptSelector",
                     "ImageUtilsInlineImagePreview", "ImageUtilsInlineCropPreview"):
            self.assertIn(name, registry)
            self.assertIn(name, self.pack.NODE_DISPLAY_NAME_MAPPINGS)
        bypass = registry["ImageUtilsLazyImageBypass"]
        self.assertEqual(bypass.RETURN_TYPES, ("IMAGE", "BOOLEAN"))
        self.assertEqual(bypass.RETURN_NAMES, ("image", "bypassed"))
        self.assertTrue(bypass.INPUT_TYPES()["required"]["passthrough_image"][1]["lazy"])
        self.assertTrue(bypass.INPUT_TYPES()["required"]["processed_image"][1]["lazy"])
        self.assertNotIn("lazy", bypass.INPUT_TYPES()["required"]["bypass"][1])
        self.assertFalse(registry["ImageUtilsInlineImagePreview"].OUTPUT_NODE)
        self.assertFalse(registry["ImageUtilsInlineCropPreview"].OUTPUT_NODE)
        self.assertEqual(registry["ImageUtilsInlineCropPreview"].RETURN_TYPES, ("IMAGE",))

    def test_lazy_bypass_requests_only_selected_input(self):
        node = self.pack.ImageUtilsLazyImageBypass()
        passthrough = object()
        detailed = object()
        self.assertEqual(node.check_lazy_status(True), ["passthrough_image"])
        self.assertEqual(node.check_lazy_status(False), ["processed_image"])
        self.assertEqual(
            node.check_lazy_status(True, passthrough_image=passthrough), [])
        self.assertEqual(
            node.check_lazy_status(False, processed_image=detailed), [])
        self.assertEqual(
            node.check_lazy_status(True, processed_image=detailed), ["passthrough_image"])
        self.assertEqual(
            node.check_lazy_status(False, passthrough_image=passthrough), ["processed_image"])
        self.assertEqual(node.route(True, passthrough_image=passthrough),
                         (passthrough, True))
        self.assertEqual(node.route(False, processed_image=detailed),
                         (detailed, False))
        with self.assertRaisesRegex(ValueError, "selected IMAGE branch"):
            node.route(True, processed_image=detailed)

    def test_prompt_priority_default_and_diagnostics(self):
        node = self.pack.ImageUtilsTagPromptSelector()
        mapping = json.dumps({
            "eyes-closed": "Closed eyelids with detailed lashes",
            "eyes-half-closed": "Half-closed eyelids, soft iris",
            "bright-green-eyes": "Bright green irises",
        })
        sidecar = json.dumps({"version": 1, "tags": ["bright-green-eyes", "eyes-closed"]})
        self.assertEqual(node.select(
            sidecar, "Ordinary natural eyes", mapping,
            "eyes-closed, eyes-half-closed, bright-green-eyes"),
            ("Closed eyelids with detailed lashes", "eyes-closed", False, 2))
        self.assertEqual(node.select(
            json.dumps({"tags": ["eyes-half-closed"]}),
            "Default", mapping, "eyes-closed,eyes-half-closed"),
            ("Half-closed eyelids, soft iris", "eyes-half-closed", False, 1))
        self.assertEqual(node.select('{"tags":["no-face"]}',"Default",mapping),
                         ("Default", "", True, 0))
        self.assertEqual(node.select('{"tags":[]}',"Default",mapping),
                         ("Default", "", True, 0))

    def test_prompt_strict_mode_and_mapping_validation(self):
        parse = self.routing.select_tag_prompt
        tags = '{"tags":["eyes-closed","bright-green-eyes","eyes-closed"]}'
        mapping = '{"eyes-closed":"closed","bright-green-eyes":"green"}'
        self.assertEqual(parse(tags, "normal", mapping)[-1], 2)
        with self.assertRaisesRegex(ValueError, "More than one mapped tag"):
            parse(tags, "normal", mapping, strict_single_match=True)
        with self.assertRaisesRegex(ValueError, "unmapped"):
            parse(tags, "normal", mapping, priority_csv="not-in-mapping")
        with self.assertRaisesRegex(ValueError, "Invalid tag prompt mapping JSON"):
            parse(tags, "normal", "{broken")
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            parse(tags, "normal", '["not", "a", "mapping"]')
        with self.assertRaisesRegex(ValueError, "must be a string"):
            parse(tags, "normal", '{"eyes-closed":42}')
        self.assertEqual(parse('{"tags":["z","a"]}',"default",'{"a":"A","z":"Z"}'),
                         ("A","a",False,2))
        self.assertEqual(parse('{"tags":["z","a"]}',"default",'{"a":"A","z":"Z"}',
                               priority_csv='"z", a'),
                         ("Z","z",False,2))

    def test_inline_preview_does_not_modify_or_replace_image_tensor(self):
        batch = FakeTensor(np.full((2, 4, 5, 3), 0.6, dtype=np.float32))
        node = self.pack.ImageUtilsInlineImagePreview()
        fake_paths = SimpleNamespace(get_temp_directory=lambda: str(self.path))
        with mock.patch.dict(sys.modules, {"folder_paths": fake_paths}):
            result = node.preview(batch, max_preview_edge=128, batch_frames=1)
        self.assertIs(result["result"][0], batch)
        self.assertEqual(len(result["ui"]["images"]), 1)
        item = result["ui"]["images"][0]
        self.assertEqual(item["type"], "temp")
        with Image.open(self.path / item["filename"]) as image:
            self.assertEqual(image.size, (5, 4))
        np.testing.assert_array_equal(batch.array, np.full((2, 4, 5, 3), .6, dtype=np.float32))
        result_disabled = node.preview(batch, enabled=False)
        self.assertEqual(result_disabled, {"ui": {"images": []}, "result": (batch,)})
        self.assertEqual(len(list(self.path.glob("*.png"))), 1)

    def test_crop_preview_handles_image_and_mask_without_activating_output_node(self):
        main = FakeTensor(np.zeros((1, 16, 16, 3), dtype=np.float32))
        crop = FakeTensor(np.full((1, 8, 12, 3), .4, dtype=np.float32))
        mask = FakeTensor(np.ones((1, 6, 10), dtype=np.float32))
        node = self.pack.ImageUtilsInlineCropPreview()
        self.assertFalse(node.OUTPUT_NODE)
        with mock.patch.dict(sys.modules, {
                "folder_paths": SimpleNamespace(get_temp_directory=lambda: str(self.path))}):
            result = node.preview(main, crop_image=crop, crop_mask=mask)
        self.assertIs(result["result"][0], main)
        images = result["ui"]["images"]
        self.assertEqual(len(images), 2)
        dims = []
        for item in images:
            with Image.open(self.path / item["filename"]) as opened:
                dims.append(opened.size)
        self.assertEqual(dims, [(12,8), (10,6)])
        self.assertTrue(all(item["type"] == "temp" for item in images))

    def test_large_images_are_only_resized_in_previews(self):
        image = FakeTensor(np.full((1, 1000, 1500, 3), .8, dtype=np.float32))
        with mock.patch.dict(sys.modules, {
                "folder_paths": SimpleNamespace(get_temp_directory=lambda: str(self.path))}):
            out = self.pack.ImageUtilsInlineImagePreview().preview(image, max_preview_edge=256)
        self.assertIs(out["result"][0], image)
        with Image.open(self.path / out["ui"]["images"][0]["filename"]) as opened:
            self.assertLessEqual(max(opened.size), 256)
            self.assertGreater(opened.size[0], opened.size[1])
        self.assertEqual(image.array.shape, (1, 1000, 1500, 3))


if __name__ == "__main__":
    unittest.main()
