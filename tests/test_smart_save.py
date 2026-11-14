"""Generation provenance and smart saver tests, runnable without ComfyUI/GPU."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_package():
    spec = importlib.util.spec_from_file_location(
        "image_utils_smart_save_tests", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pkg
    spec.loader.exec_module(pkg)
    return pkg


class FakeTensor:
    def __init__(self, data):
        self.data = data
        self.shape = data.shape
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return self.data


class FakeBatch:
    def __init__(self, n=1):
        self.data = np.full((n, 12, 14, 3), .6, dtype=np.float32)
        self.shape = self.data.shape
    def __len__(self):
        return self.data.shape[0]
    def __iter__(self):
        return (FakeTensor(image) for image in self.data)
    def __getitem__(self, index):
        return FakeTensor(self.data[index])


class SmartSaverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.fake = SimpleNamespace(
            get_output_directory=lambda: str(self.output),
            get_save_image_path=lambda prefix, base, width, height:
                (str(self.output), prefix, 1, "", prefix),
        )
        self.pack = load_package()

    def saver(self):
        with mock.patch.dict(sys.modules, {"folder_paths": self.fake}):
            return self.pack.ImageUtilsSaveImageWithSidecar()

    def init(self, positive="A realistic closeup", negative="blurry", seed=42):
        return json.loads(self.pack.ImageUtilsSidecarInitialize().initialize(
            positive, negative, seed, "Krea 2", '{"steps":10}')[0])

    def save(self, json_doc=None, count=1, **kw):
        opts = {"filename_template": "%input_name%_%stage%_%tracked_count%",
                "source_name": "/workspace/input/culled_for_detailing_0087.png",
                "stage": "after_detailer_pipe_and_upscaled"}
        opts.update(kw)
        with mock.patch.dict(sys.modules, {"folder_paths": self.fake}):
            return self.saver().save_images(
                FakeBatch(count),
                sidecar_json=json.dumps(json_doc) if json_doc is not None else None,
                include_current_workflow_in_history=False, **opts)

    def test_initializer_captures_resolved_prompt_seed_model(self):
        cls = self.pack.NODE_CLASS_MAPPINGS["ImageUtilsSidecarInitialize"]
        self.assertEqual(cls.RETURN_TYPES, ("STRING",))
        self.assertIn("positive_prompt", cls.INPUT_TYPES()["required"])
        doc = self.init("An actual chosen PromptLibrary STRING", "bad anatomy", 123)
        self.assertEqual(doc["prompts"]["generation"]["positive"],
                         "An actual chosen PromptLibrary STRING")
        self.assertEqual(doc["prompts"]["generation"]["negative"], "bad anatomy")
        self.assertEqual(doc["origin"]["generation"]["seed"], 123)
        self.assertEqual(doc["origin"]["generation"]["model"], "Krea 2")
        self.assertEqual(doc["origin"]["generation"]["settings"], {"steps": 10})
        self.assertEqual(doc["history"], [])
        self.assertEqual(doc["tags"], [])
        self.assertEqual(doc["controls"], {})
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            self.pack.ImageUtilsSidecarInitialize().initialize("a", settings_json="{bad")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            self.pack.ImageUtilsSidecarInitialize().initialize("a", settings_json="[1,2]")
        self.assertNotIn("seed", json.loads(self.pack.ImageUtilsSidecarInitialize().initialize(
            "prompt")[0])["origin"]["generation"])

    def test_saver_template_uses_filename_and_tracked_counter_and_copies_origin(self):
        source = self.init()
        source["tags"] = ["no-eyes"]
        source["controls"] = {"face_detailer": {"grow": 12}}
        original = json.loads(json.dumps(source))
        result = self.save(source)
        item = result["ui"]["images"][0]
        filename = "culled_for_detailing_0087_after_detailer_pipe_and_upscaled_0087.png"
        self.assertEqual(item["filename"], filename)
        path = self.output / filename
        self.assertEqual(result["ui"]["mr_saved_paths"][0], str(path))
        self.assertEqual(result["ui"]["mr_saved_previews"], [{
            "filename": filename, "subfolder": "", "type": "output",
            "preview_available": True, "display_path": str(path)
        }])
        sidecar = json.loads(path.with_suffix(".sidecar").read_text())
        with Image.open(path) as png:
            self.assertEqual(json.loads(png.info["image_sidecar"]), sidecar)
        self.assertEqual(sidecar["prompts"]["generation"]["positive"],
                         "A realistic closeup")
        self.assertEqual(sidecar["tags"], ["no-eyes"])
        self.assertEqual(sidecar["controls"]["face_detailer"]["grow"], 12)
        self.assertEqual(sidecar["origin"]["tracking_id"], "0087")
        self.assertEqual(sidecar["origin"]["source_filename"], "culled_for_detailing_0087.png")
        self.assertEqual(sidecar["origin"]["generation"], original["origin"]["generation"])
        self.assertEqual(sidecar["history"][-1]["processing_stage"],
                         "after_detailer_pipe_and_upscaled")
        self.assertEqual(sidecar["history"][-1]["revision"], 1)
        self.assertEqual(source, original)

    def test_collision_allocates_revisions_without_overwriting_original(self):
        original = self.init()
        a = self.save(original)
        first = Path(a["ui"]["mr_saved_paths"][0])
        initial_bytes = first.read_bytes()
        b = self.save(original)
        second = Path(b["ui"]["mr_saved_paths"][0])
        self.assertTrue(second.name.endswith("_v02.png"))
        self.assertEqual(first.read_bytes(), initial_bytes)
        self.assertEqual(json.loads(second.with_suffix(".sidecar").read_text())
                         ["origin"]["tracking_id"], "0087")
        with self.assertRaises(FileExistsError):
            self.save(original, collision_policy="error")

    def test_existing_origin_tracking_is_preferred_over_renamed_source(self):
        original = self.init()
        original["origin"]["tracking_id"] = "0024"
        original["origin"]["source_filename"] = "original_0024.png"
        item = self.save(original, source_name="detailed_file_9911.png")
        path = Path(item["ui"]["mr_saved_paths"][0])
        self.assertEqual(path.name, "detailed_file_9911_after_detailer_pipe_and_upscaled_0024.png")
        doc = json.loads(path.with_suffix(".sidecar").read_text())
        self.assertEqual(doc["origin"]["tracking_id"], "0024")
        self.assertEqual(doc["origin"]["source_filename"], "original_0024.png")

    def test_filename_aligned_counter_is_independent_of_immutable_lineage(self):
        original = self.init()
        original["origin"]["tracking_id"] = "0001"
        original["origin"]["source_filename"] = "generated_0001.png"
        result = self.save(
            original,
            source_name="curated_set_0087.png",
            filename_template="%input_name%_%stage%_%aligned_counter%")
        file = Path(result["ui"]["mr_saved_paths"][0])
        self.assertEqual(
            file.name,
            "curated_set_0087_after_detailer_pipe_and_upscaled_0087.png")
        saved = json.loads(file.with_suffix(".sidecar").read_text())
        self.assertEqual(saved["origin"]["tracking_id"], "0001")
        self.assertEqual(saved["history"][-1]["tracking_id"], "0001")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.save(original, source_name="curated_set_0087.png", tracking_id="0087")

    def test_prefix_token_uses_filename_prefix_for_generation_names(self):
        options = {"source_name": "", "filename_prefix": "image_gen_2k",
                   "filename_template": "%prefix%_%counter%",
                   "output_directory": "trial2k", "stage": "generation"}
        a = Path(self.save(None, **options)["ui"]["mr_saved_paths"][0])
        b = Path(self.save(None, **options)["ui"]["mr_saved_paths"][0])
        self.assertEqual(a.name, "image_gen_2k_0000.png")
        self.assertEqual(b.name, "image_gen_2k_0001.png")
        self.assertEqual(a.parent, self.output / "trial2k")
        self.assertTrue(a.with_suffix(".sidecar").is_file())
        with Image.open(a) as img:
            embedded = json.loads(img.info["image_sidecar"])
        self.assertEqual(json.loads(a.with_suffix(".sidecar").read_text()), embedded)

    def test_custom_templates_without_prefix_token_remain_unchanged(self):
        original = self.init()
        filename = Path(self.save(original, filename_prefix="image_gen_2k",
                       filename_template="%input_name%_%tracked_count%")
                        ["ui"]["mr_saved_paths"][0]).name
        self.assertEqual(filename, "culled_for_detailing_0087_0087.png")

    def test_prefix_token_accepts_subdirectory_prefix_as_basename(self):
        from image_utils_smart_save_tests.save_naming import expand_filename
        self.assertEqual(expand_filename("%prefix%_%counter%", prefix="foo/bar",
                         counter=7), "bar_0007.png")
        with self.assertRaisesRegex(ValueError, "paths or unsafe"):
            expand_filename("%prefix%_%counter%", prefix="name:bad", counter=7)

    def test_source_without_counter_uses_sequential_ids(self):
        opts = {"source_name": "untagged.png",
                "filename_template": "%input_name%_%tracked_count%"}
        a = Path(self.save(None, **opts)["ui"]["mr_saved_paths"][0])
        b = Path(self.save(None, **opts)["ui"]["mr_saved_paths"][0])
        self.assertEqual(a.name, "untagged_0000.png")
        self.assertEqual(b.name, "untagged_0001.png")

    def test_without_json_saver_initializes_from_connected_prompt_and_seed(self):
        r = self.save(None, filename_template="%date%_%counter%", positive_prompt="Prompt from Krea",
                      negative_prompt="blur", seed=4343, model_name="Krea2",
                      settings_json='{"denoise": 0.7}')
        path = Path(r["ui"]["mr_saved_paths"][0])
        doc = json.loads(path.with_suffix(".sidecar").read_text())
        self.assertEqual(doc["prompts"]["generation"]["positive"], "Prompt from Krea")
        self.assertEqual(doc["origin"]["generation"]["seed"], 4343)
        self.assertEqual(doc["origin"]["tracking_id"], "0087")
        self.assertEqual(doc["origin"]["generation"]["settings"], {"denoise": 0.7})

    def test_output_directory_safe_paths_and_subfolders(self):
        save = self.save(self.init(), output_directory="Detailed",
                         filename_template="%input_name%_%tracked_count%")
        self.assertEqual(Path(save["ui"]["mr_saved_paths"][0]).parent,
                         self.output / "Detailed")
        self.assertEqual(save["ui"]["images"][0]["subfolder"], "Detailed")
        for folder in ("../unsafe", str(self.root / "outside")):
            with self.subTest(folder=folder), self.assertRaisesRegex(ValueError, "outside"):
                self.save(self.init(), output_directory=folder)
        external = self.root / "trusted"
        with mock.patch.dict(os.environ, {"IMAGE_UTILS_ALLOWED_OUTPUT_DIRS": str(external)}):
            result = self.save(self.init(), output_directory=str(external))
        self.assertEqual(Path(result["ui"]["mr_saved_paths"][0]).parent, external)
        self.assertEqual(result["ui"]["images"], [])
        self.assertEqual(len(result["ui"]["mr_saved_previews"]), 1)
        self.assertFalse(result["ui"]["mr_saved_previews"][0]["preview_available"])
        self.assertEqual(result["ui"]["mr_saved_previews"][0]["display_path"],
                         result["ui"]["mr_saved_paths"][0])

    def test_batch_outputs_unique_names_and_tracking(self):
        result = self.save(self.init(), count=3)
        names = [Path(p).name for p in result["ui"]["mr_saved_paths"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(names[0].endswith("_b000.png"))
        self.assertTrue(names[1].endswith("_b001.png"))
        for f in names:
            self.assertEqual(json.loads((self.output / f).with_suffix(".sidecar").read_text())
                             ["origin"]["tracking_id"], "0087")

    def test_corrupt_old_widget_values_refused_before_any_file_is_saved(self):
        invalid = [
            ({"counter_padding": 0}, "counter_padding"),
            ({"counter_start": float("nan")}, "counter_start"),
            ({"collision_policy": -1}, "collision_policy"),
            ({"stage": ""}, "stage"),
            ({"tracking_id": 4}, "tracking_id"),
            ({"seed": "control after generate"}, "seed"),
        ]
        for updates, expected in invalid:
            with self.subTest(invalid=updates):
                with self.assertRaisesRegex(ValueError,
                                             "invalid/misaligned.*" + expected):
                    self.save(None, **updates)
                self.assertFalse(list(self.output.glob("*.png")))
                self.assertFalse(list(self.output.glob("*.sidecar")))

    def test_generation_prompt_multiline_fields_are_explicitly_labeled(self):
        spec = self.pack.ImageUtilsSaveImageWithSidecar.INPUT_TYPES()
        negative = spec["optional"]["negative_prompt"][1]
        settings = spec["optional"]["settings_json"][1]
        self.assertTrue(negative["multiline"])
        self.assertTrue(settings["multiline"])
        self.assertIn("NEGATIVE PROMPT", negative["placeholder"])
        self.assertIn("GENERATION SETTINGS", settings["placeholder"])
        self.assertEqual(settings["default"], "{}")
        self.assertEqual(negative["default"], "")

    def test_optional_sidecar_keeps_legacy_naming_and_prompt_metadata(self):
        with mock.patch.dict(sys.modules, {"folder_paths": self.fake}):
            result = self.saver().save_images(
                FakeBatch(1), sidecar_json=None,
                prompt={"node": {"class_type": "Anything"}},
                extra_pnginfo={"workflow": {"nodes": []}})
        self.assertEqual(result["ui"]["images"][0]["filename"], "ImageUtils_00001_.png")
        with Image.open(self.output / "ImageUtils_00001_.png") as png:
            self.assertIn("workflow", png.info)
            self.assertIn("prompt", png.info)
            self.assertIn("image_sidecar", png.info)
        record = json.loads((self.output / "ImageUtils_00001_.sidecar").read_text())
        self.assertEqual(record["origin"]["tracking_id"], "0001")
        self.assertEqual(record["prompts"], {})


if __name__ == "__main__":
    unittest.main()
