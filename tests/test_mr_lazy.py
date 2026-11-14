"""MR lazy LC detailer compatibility and diagnostic tests (no GPU needed)."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_nodes():
    name = "image_utils_mr_test_package"
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


class FakeLC:
    RETURN_TYPES = ("LC_PIPE", "IMAGE", "MASK")
    constructed = 0

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pipe": ("LC_PIPE",),
                "prompt": ("STRING", {"default": "face"}),
            },
            "optional": {"image": ("IMAGE",)},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, sam3_model=None):
        return True

    def __init__(self):
        type(self).constructed += 1
        self.calls = []

    def run(self, pipe, image=None, **kw):
        self.calls.append((pipe, image, kw))
        result = {"upstream": "preserved"}
        return {
            "ui": {"lc_inpaint": [
                {"filename": "before.png", "type": "temp", "subfolder": ""},
                {"filename": "after.png", "type": "temp", "subfolder": ""},
            ], "lc_inpaint_note": ["1 redrawn"]},
            "result": (pipe, image, result),
        }


class MRTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_nodes()

    def test_registration_and_non_output_detailers(self):
        reg = self.pack.NODE_CLASS_MAPPINGS
        self.assertEqual(len(reg), 15)
        for name in ("ImageUtilsMRLazySmartDetailerPipe",
                     "ImageUtilsMRLazyCharacterDetailerPipe"):
            cls = reg[name]
            self.assertFalse(cls.OUTPUT_NODE)
            self.assertEqual(cls.RETURN_TYPES, ("LC_PIPE", "IMAGE", "MASK"))
            self.assertEqual(cls.RETURN_NAMES, ("pipe", "image", "mask"))
            self.assertIn(name, self.pack.NODE_DISPLAY_NAME_MAPPINGS)
        self.assertFalse(self.pack.MRInlineVRAMClear.OUTPUT_NODE)
        self.assertTrue(self.pack.MRConditionalPreviewSink.OUTPUT_NODE)
        self.assertEqual(self.pack.WEB_DIRECTORY, "./web")

    def test_adapter_delegates_to_existing_lonecat_without_mutating_it(self):
        FakeLC.constructed = 0
        registry = SimpleNamespace(NODE_CLASS_MAPPINGS={
            "LCSmartInpaintPipe": FakeLC,
            "LCCharacterDetailerPipe": FakeLC,
        })
        with mock.patch.dict(sys.modules, {"nodes": registry}):
            for cls in (self.pack.MRLazySmartDetailerPipe,
                        self.pack.MRLazyCharacterDetailerPipe):
                self.assertIn("prompt", cls.INPUT_TYPES()["required"])
                self.assertTrue(cls.VALIDATE_INPUTS(sam3_model="sam3"))
                instance = cls()
                pipe = {"_type": "LC_PIPE", "image": "orig", "lc_protect": "mask"}
                response = instance.run(pipe=pipe, image="src", prompt="eyes")
                self.assertIs(response["result"][0], pipe)
                self.assertEqual(response["ui"]["images"][0]["filename"], "after.png")
                self.assertEqual(len(response["ui"]["lc_inpaint"]), 2)
                second = instance.run(pipe=pipe, image="src", prompt="hands")
                self.assertEqual(second["result"][0], pipe)
                self.assertEqual(len(instance._upstream_instance.calls), 2)
            self.assertTrue(FakeLC.OUTPUT_NODE if hasattr(FakeLC, "OUTPUT_NODE") else True)
            self.assertEqual(FakeLC.constructed, 2)

    def test_missing_or_changed_upstream_is_clear_error(self):
        with mock.patch.dict(sys.modules, {
            "nodes": SimpleNamespace(NODE_CLASS_MAPPINGS={}),
        }):
            self.assertEqual(
                self.pack.MRLazySmartDetailerPipe.INPUT_TYPES()["required"]["pipe"],
                ("LC_PIPE",))
            with self.assertRaisesRegex(RuntimeError, "Missing LoneCat node"):
                self.pack.MRLazySmartDetailerPipe().run(pipe={})

        class WrongLC(FakeLC):
            RETURN_TYPES = ("IMAGE",)
        with mock.patch.dict(sys.modules, {
            "nodes": SimpleNamespace(NODE_CLASS_MAPPINGS={"LCSmartInpaintPipe": WrongLC}),
        }):
            with self.assertRaisesRegex(RuntimeError, "changed RETURN_TYPES"):
                self.pack.MRLazySmartDetailerPipe().run(pipe={})

    def test_sink_lazily_requests_connected_inputs_only_when_selected(self):
        node = self.pack.MRConditionalPreviewSink()
        dynprompt = SimpleNamespace(get_node=lambda node_id: {
            "inputs": {"bypass": ["bool", 0], "image_1": ["detailer", 1],
                       "mask_2": ["detailer", 2]},
        })
        args = {"unique_id": "15", "dynprompt": dynprompt}
        self.assertEqual(node.check_lazy_status(True, **args), [])
        self.assertEqual(node.check_lazy_status(False, **args),
                         ["image_1", "mask_2"])
        self.assertEqual(node.check_lazy_status(
            False, image_1="already calculated", **args), ["mask_2"])
        self.assertTrue(node.INPUT_TYPES()["optional"]["image_1"][1]["lazy"])
        self.assertTrue(node.INPUT_TYPES()["optional"]["mask_2"][1]["lazy"])

    def test_sink_skip_does_not_touch_previews(self):
        node = self.pack.MRConditionalPreviewSink()
        with mock.patch.object(
                self.pack,
                "ImageUtilsInlineCropPreview",
                side_effect=AssertionError("Should never preview")):
            result = node.sink(bypass=True, stage="Eyes")
        self.assertEqual(result["ui"]["images"], [])
        self.assertEqual(
            result["ui"]["mr_preview_status"][0],
            {"stage": "Eyes", "state": "skipped"})
        self.assertEqual(result["result"], ())

    def test_sink_selected_previews_only_provided_tensors(self):
        node = self.pack.MRConditionalPreviewSink()
        with tempfile.TemporaryDirectory() as tmp:
            image = FakeTensor(np.zeros((1, 32, 48, 3), dtype=np.float32))
            mask = FakeTensor(np.zeros((1, 32, 48), dtype=np.float32))
            fake_paths = SimpleNamespace(get_temp_directory=lambda: tmp)
            with mock.patch.dict(sys.modules, {"folder_paths": fake_paths}):
                result = node.sink(bypass=False, stage="Face",
                                   image_1=image, mask_1=mask)
            self.assertEqual(len(result["ui"]["images"]), 2)
            self.assertEqual(
                result["ui"]["mr_preview_status"][0],
                {"stage": "Face", "state": "selected"})
            self.assertEqual(len(list(Path(tmp).glob("*.png"))), 2)

    def test_inline_clear_is_non_output_passthrough(self):
        node = self.pack.MRInlineVRAMClear()
        pipe = {"_type": "LC_PIPE", "image": "unchanged"}
        calls = []
        fake_cuda = SimpleNamespace(
            is_available=lambda: True,
            empty_cache=lambda: calls.append("empty"),
            ipc_collect=lambda: calls.append("ipc"))
        with mock.patch.dict(sys.modules, {
            "torch": SimpleNamespace(cuda=fake_cuda),
        }):
            result = node.clear(pipe)
        self.assertIs(result[0], pipe)
        self.assertEqual(calls, ["empty", "ipc"])


if __name__ == "__main__":
    unittest.main()
