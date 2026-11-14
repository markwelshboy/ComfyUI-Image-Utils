"""Regression tests. No ComfyUI, NumPy, Torch or network access required."""
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("image_utils_sidecar", ROOT / "sidecar.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def nodes():
    import sys
    spec = importlib.util.spec_from_file_location(
        "image_utils_test_package", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)]
    )
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.api = module()

    def test_spaces_in_names_and_missing_sidecars(self):
        path = self.dir / "image with spaces.png"
        path.write_bytes(b"not decoded; only path needed")
        obj, found, side = self.api.read_sidecar(path)
        self.assertFalse(found)
        self.assertEqual(obj["tags"], [])
        self.assertEqual(Path(side), self.dir / "image with spaces.sidecar")
        self.assertEqual(self.api.sidecar_candidates(path)[1], self.dir / "image with spaces.sidecar")

    def test_json_fields_and_stem_sidecar(self):
        path = self.dir / "image with spaces.png"
        sidecar = path.with_suffix(".sidecar")
        data = {"version":1,"tags":["eyes-closed"],"controls":{
            "eye_detailer":{"enabled":False,"denoise":0.2},
            "eye detailer":{"enabled":"true"}},"prompts":{"eye_detailer":"Closed lids"}}
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        loaded, exists, found_path = self.api.read_sidecar(path)
        self.assertTrue(exists)
        self.assertEqual(found_path, str(sidecar))
        self.assertEqual(self.api.get_field(loaded,"controls.eye_detailer.enabled"), (False,True))
        self.assertEqual(self.api.get_field(loaded,'controls["eye detailer"].enabled'), ("true",True))
        self.assertEqual(self.api.get_field(loaded,"tags[0]"), ("eyes-closed",True))
        self.assertEqual(self.api.get_field(loaded,"tags[9]"), (None,False))
        self.assertEqual(self.api.get_field(loaded,"missing"), (None,False))
        self.assertEqual(self.api.typed_field(loaded,"controls.eye_detailer.enabled"),
                         ("false", False, 0, 0.0, True))
        self.assertEqual(self.api.typed_field(loaded,"controls.eye_detailer.denoise"),
                         ("0.2", True, 0, 0.2, True))
        self.assertEqual(self.api.typed_field(loaded,"unknown", "default", True, 9, 4.5),
                         ("default", True, 9, 4.5, False))
        self.assertTrue(self.api.has_tag(loaded,"eyes-closed"))
        self.assertFalse(self.api.has_tag(loaded,"eyes-half-closed"))

    def test_full_filename_fallback_overrides_stem_sidecar(self):
        png = self.dir / "img.png"
        jpg = self.dir / "img.jpg"
        for path, tags in ((png,["png"]),(jpg,["jpg"])):
            Path(str(path)+".sidecar").write_text(
                json.dumps({"version":1,"tags":tags}), encoding="utf-8")
        png.with_suffix(".sidecar").write_text(
            json.dumps({"version":1,"tags":["incorrect"]}), encoding="utf-8")
        self.assertEqual(self.api.read_sidecar(png)[0]["tags"],["png"])
        self.assertEqual(self.api.read_sidecar(jpg)[0]["tags"],["jpg"])

    def test_bad_json_and_unexpected_schema_are_explicit_errors(self):
        target=self.dir/"image.png"
        target.with_suffix(".sidecar").write_text("{broken")
        with self.assertRaisesRegex(ValueError,"Invalid sidecar JSON"):
            self.api.read_sidecar(target)
        target.with_suffix(".sidecar").write_text('{"version": 3}')
        with self.assertRaisesRegex(ValueError,"Unsupported sidecar version"):
            self.api.read_sidecar(target)
        target.with_suffix(".sidecar").write_text('{"version":1,"tags":"eyes-closed"}')
        with self.assertRaisesRegex(ValueError,"list of strings"):
            self.api.read_sidecar(target)

    def test_sidecar_hash_changes_without_image_modification(self):
        source=self.dir/"img.png"
        signature1=self.api.sidecar_signature(source)
        path=source.with_suffix(".sidecar")
        path.write_text('{"tags":[]}')
        signature2=self.api.sidecar_signature(source)
        path.write_text('{"tags":["eyes-closed"]}')
        signature3=self.api.sidecar_signature(source)
        self.assertNotEqual(signature1,signature2)
        self.assertNotEqual(signature2,signature3)

    def test_boolean_coercion_and_prompt_fallback(self):
        self.assertFalse(self.api.bool_value("false"))
        self.assertFalse(self.api.bool_value("0"))
        self.assertTrue(self.api.bool_value("True"))
        self.assertEqual(self.api.conditional_prompt("detailed iris", "no iris", True),
                         ("no iris", True))
        self.assertEqual(self.api.conditional_prompt("detailed iris", "no iris", False),
                         ("detailed iris", False))
        self.assertEqual(self.api.conditional_prompt("detailed iris", "", True),
                         ("detailed iris", False))

    def test_comfy_nodes_have_correct_static_types(self):
        pack=nodes()
        mapping=pack.NODE_CLASS_MAPPINGS
        self.assertEqual(len(mapping),16)
        loader=mapping["ImageUtilsSidecarLoader"]()
        self.assertEqual(mapping["ImageUtilsSidecarLoader"].RETURN_TYPES,
                         ("STRING","BOOLEAN","STRING"))
        image=self.dir/"image with spaces.png"
        image.with_suffix(".sidecar").write_text(
            '{"version":1,"tags":["eyes-closed"],"controls":{"eye_detailer":{"enabled":false}}}')
        json_text,exists,sidecar=loader.load(str(image))
        self.assertTrue(exists)
        self.assertEqual(json.loads(json_text)["tags"],["eyes-closed"])
        field=mapping["ImageUtilsJsonFieldExtractor"]()
        self.assertEqual(field.extract(json_text,"controls.eye_detailer.enabled"),
                         ("false", False, 0, 0.0, True))
        tags=mapping["ImageUtilsJsonTagChecker"]()
        self.assertEqual(tags.check(json_text,"eyes-closed"),(True,))
        prompt=mapping["ImageUtilsConditionalPrompt"]()
        self.assertEqual(prompt.select("open irises","closed lids",True),
                         ("closed lids", True))


    def test_append_processing_event_retains_original_prompt_and_workflow(self):
        orig = {
            "version": 1, "tags": ["eyes-closed"], "controls": {}, "prompts": {},
            "origin": {"source_filename": "original.png",
                       "seeds": [{"value": "12345"}],
                       "metadata": {"workflow": {"nodes": ["original"]},
                                    "prompt": {"3": {"inputs": {"seed": 12345}}}}},
            "history": [],
        }
        first = self.api.append_processing_event(
            orig, stage="eye-detailer",
            actual_prompt="Closed lids, natural lashes, no visible iris",
            input_image_path="/workspace/input/image with spaces.png",
            settings_json='{"denoise": 0.18}', seed=5678)
        self.assertEqual(first["origin"], orig["origin"])
        self.assertEqual(first["history"][0]["actual_prompt"],
                         "Closed lids, natural lashes, no visible iris")
        self.assertEqual(first["history"][0]["settings"]["denoise"], .18)
        second = self.api.append_processing_event(
            first, stage="face-detailer", actual_prompt="Natural skin pores")
        self.assertEqual(len(second["history"]), 2)
        self.assertEqual(second["origin"], orig["origin"])

    def test_embedded_png_recovers_when_sidecar_missing(self):
        from PIL import Image, PngImagePlugin
        path = self.dir / "detail result.png"
        saved = {
            "version": 1, "tags": ["eyes-closed"], "controls": {}, "prompts": {},
            "origin": {"source_filename": "original.png", "seeds": [{"value": "99"}]},
            "history": [{"stage": "eye-detailer", "actual_prompt": "Closed lids"}],
        }
        info = PngImagePlugin.PngInfo()
        info.add_itxt("krea_sidecar", json.dumps(saved), zip=True)
        Image.new("RGB", (4, 4), color=(80, 100, 130)).save(path, pnginfo=info)
        actual, found, selected = self.api.read_sidecar(path)
        self.assertTrue(found)
        self.assertEqual(actual["origin"], saved["origin"])
        self.assertEqual(actual["history"], saved["history"])
        self.assertEqual(selected, str(path.with_suffix(".sidecar")))
        external = path.with_suffix(".sidecar")
        external.write_text(json.dumps({**saved, "tags": ["updated"]}))
        self.assertEqual(self.api.read_sidecar(path)[0]["tags"], ["updated"])
        external.unlink()
        self.assertEqual(self.api.read_sidecar(path)[0]["tags"], ["eyes-closed"])


    def test_new_metadata_key_takes_priority_over_legacy_on_same_png(self):
        from PIL import Image, PngImagePlugin
        path = self.dir / "both formats.png"
        info = PngImagePlugin.PngInfo()
        info.add_itxt("krea_sidecar", json.dumps({"version": 1,
            "tags": ["old"], "origin": {"source_filename": "old.png"}}), zip=True)
        info.add_itxt("image_sidecar", json.dumps({"version": 1,
            "tags": ["new"], "origin": {"source_filename": "new.png"}}), zip=True)
        Image.new("RGB", (2, 2)).save(path, pnginfo=info)
        data, found, _ = self.api.read_sidecar(path)
        self.assertTrue(found)
        self.assertEqual(data["origin"]["source_filename"], "new.png")
        self.assertEqual(data["tags"], ["new"])

    def test_embedded_backup_larger_than_pillow_default_text_limit(self):
        from PIL import Image, PngImagePlugin
        large = {
            "version": 1, "tags": [], "controls": {}, "prompts": {},
            "origin": {"metadata": {"prompt": {"long_text": "A" * 1_300_000}}},
            "history": [],
        }
        path = self.dir / "large generated.png"
        meta = PngImagePlugin.PngInfo()
        meta.add_itxt("image_sidecar", json.dumps(large), zip=True)
        Image.new("RGB", (2, 2)).save(path, pnginfo=meta)
        recovered, found, sidecar_path = self.api.read_sidecar(path)
        self.assertTrue(found)
        self.assertEqual(recovered["origin"], large["origin"])
        self.assertFalse(Path(sidecar_path).exists())

    def test_save_image_with_sidecar_and_embedded_backup(self):
        # Minimal folder_paths stub, using real numpy/Pillow to verify PNG text
        # and sidecar output. Does not need PyTorch/ComfyUI at test time.
        import numpy as np
        import sys
        from PIL import Image
        from types import SimpleNamespace
        fake = SimpleNamespace(
            get_output_directory=lambda: str(self.dir),
            get_save_image_path=lambda prefix, base, width, height:
                (str(self.dir), "detailer_%batch_num%", 1, "", prefix),
        )
        class FakeTensor:
            def __init__(self, array):
                self.array = array
                self.shape = array.shape
            def detach(self): return self
            def cpu(self): return self
            def numpy(self): return self.array
        class FakeBatch:
            def __init__(self, array):
                self.image = FakeTensor(array)
            def __getitem__(self, index): return self.image
            def __iter__(self): return iter([self.image])
        first = {
            "version": 1, "tags": ["eyes-closed"], "controls": {}, "prompts": {},
            "origin": {"metadata": {"prompt": {"nodes": ["original"]}},
                       "seeds": [{"value": "101"}]},
            "history": [{"stage": "eye-detailer", "actual_prompt": "No visible iris"}],
        }
        with mock.patch.dict(sys.modules, {"folder_paths": fake}):
            pack = nodes()
            saver = pack.NODE_CLASS_MAPPINGS["ImageUtilsSaveImageWithSidecar"]()
            result = saver.save_images(
                FakeBatch(np.ones((4, 4, 3), dtype=np.float32) * .4),
                json.dumps(first), filename_prefix="detailer",
                prompt={"3": {"class_type": "KSampler"}},
                extra_pnginfo={"workflow": {"nodes": ["detailer"]}},
            )
        item = result["ui"]["images"][0]
        image = self.dir / item["filename"]
        sidecar = image.with_suffix(".sidecar")
        self.assertTrue(image.exists())
        self.assertTrue(sidecar.exists())
        with Image.open(image) as raw:
            self.assertEqual(json.loads(raw.info["prompt"])["3"]["class_type"], "KSampler")
            self.assertEqual(json.loads(raw.info["workflow"])["nodes"], ["detailer"])
            embedded = json.loads(raw.info["image_sidecar"])
            self.assertNotIn("krea_sidecar", raw.info)
        disk = json.loads(sidecar.read_text())
        self.assertEqual(embedded, disk)
        self.assertEqual(embedded["origin"], first["origin"])
        self.assertEqual(embedded["history"][0], first["history"][0])
        self.assertEqual(embedded["history"][-1]["stage"], "image-save")
        self.assertEqual(embedded["history"][-1]["workflow"], {"nodes": ["detailer"]})
        self.assertEqual(self.api.read_sidecar(image)[0]["history"], disk["history"])
        sidecar.unlink()
        self.assertEqual(self.api.read_sidecar(image)[0]["origin"], first["origin"])



if __name__=="__main__":
    unittest.main()
