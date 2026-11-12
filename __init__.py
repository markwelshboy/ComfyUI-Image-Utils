"""Generic ComfyUI image-sidecar and conditional control nodes.

A standard ComfyUI STRING connection accepts shootthesound's Sequential Image
Loader's 'file_path' output. Everything runs against the Python backend's
filesystem, including when the backend is hosted on a pod.

This package deliberately has no frontend-JavaScript/socket monkeypatching.
Its output types are always stable when the JSON schema changes.
"""
from .sidecar import (
    read_sidecar, typed_field, has_tag, conditional_prompt, sidecar_signature,
    append_processing_event, validate_document, load_document
)

CATEGORY = "Image Utils / Sidecars"


class ImageUtilsSidecarLoader:
    """Load a sibling JSON sidecar given an absolute image filename."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image_path": ("STRING", {
            "forceInput": True, "tooltip": "Absolute file_path from Sequential Image Loader."
        })}}

    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("json", "exists", "sidecar_path")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, image_path):
        return sidecar_signature(image_path)

    def load(self, image_path):
        import json
        document, exists, path = read_sidecar(image_path)
        return json.dumps(document, ensure_ascii=False), exists, path


class ImageUtilsJsonFieldExtractor:
    """One JSON path with fixed typed outputs and a found flag."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "json": ("STRING", {"forceInput": True}),
            "field_path": ("STRING", {"default": "controls.eye_detailer.enabled"}),
            "default_string": ("STRING", {"default": ""}),
            "default_boolean": ("BOOLEAN", {"default": False}),
            "default_int": ("INT", {"default": 0, "min": -2147483647, "max": 2147483647}),
            "default_float": ("FLOAT", {"default": 0.0, "min": -1000000.0, "max": 1000000.0}),
        }}

    RETURN_TYPES = ("STRING", "BOOLEAN", "INT", "FLOAT", "BOOLEAN")
    RETURN_NAMES = ("text", "boolean", "integer", "number", "found")
    FUNCTION = "extract"
    CATEGORY = CATEGORY

    def extract(self, json, field_path, default_string="", default_boolean=False,
                default_int=0, default_float=0.0):
        return typed_field(json, field_path, default_string, default_boolean,
                           default_int, default_float)


class ImageUtilsJsonTagChecker:
    """Check whether the 'tags' array contains a specific condition."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "json": ("STRING", {"forceInput": True}),
            "tag": ("STRING", {"default": "eyes-closed"}),
        }}

    RETURN_TYPES = ("BOOLEAN",)
    RETURN_NAMES = ("has_tag",)
    FUNCTION = "check"
    CATEGORY = CATEGORY

    def check(self, json, tag):
        return (has_tag(json, tag),)


class ImageUtilsConditionalPrompt:
    """Return a fully formed prompt, avoiding Any Switch None/empty semantics."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "default_prompt": ("STRING", {"forceInput": True,
                                           "tooltip": "Connect your existing default text prompt."}),
            "override_prompt": ("STRING", {"default": "Closed eyelids, natural lashes, no iris",
                                            "multiline": True}),
            "condition": ("BOOLEAN", {"forceInput": True}),
        }}

    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("prompt", "using_override")
    FUNCTION = "select"
    CATEGORY = CATEGORY

    def select(self, default_prompt, override_prompt, condition):
        return conditional_prompt(default_prompt, override_prompt, condition)



class ImageUtilsAppendProcessingEvent:
    """Record the actual prompt chosen by the detailer, without losing origin."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sidecar_json": ("STRING", {"forceInput": True}),
            "stage": ("STRING", {"default": "eye-detailer"}),
            "actual_prompt": ("STRING", {"forceInput": True}),
            "settings_json": ("STRING", {"default": "{}", "multiline": True}),
        }, "optional": {
            "input_image_path": ("STRING", {"forceInput": True}),
            "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("sidecar_json",)
    FUNCTION = "append"
    CATEGORY = CATEGORY

    def append(self, sidecar_json, stage, actual_prompt, settings_json="{}",
               input_image_path="", seed=-1):
        import json
        doc = append_processing_event(
            sidecar_json, stage=stage, actual_prompt=actual_prompt,
            settings_json=settings_json, input_image_path=input_image_path, seed=seed)
        return (json.dumps(doc, ensure_ascii=False),)


class ImageUtilsSaveImageWithSidecar:
    """Save PNG plus .sidecar, and embed a backup in PNG's image_sidecar iTXt.

    Hidden prompt and extra_pnginfo preserve regular ComfyUI image metadata.
    The sidecar JSON is the source of provenance and processing history.
    """
    OUTPUT_NODE = True
    CATEGORY = CATEGORY
    FUNCTION = "save_images"
    RETURN_TYPES = ()

    def __init__(self):
        import folder_paths
        self.output_dir = folder_paths.get_output_directory()

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "sidecar_json": ("STRING", {"forceInput": True}),
            "filename_prefix": ("STRING", {"default": "ImageUtils"}),
            "include_current_workflow_in_history": ("BOOLEAN", {"default": True}),
        }, "hidden": {
            "prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO",
        }}

    def save_images(self, images, sidecar_json, filename_prefix="ImageUtils",
                    include_current_workflow_in_history=True,
                    prompt=None, extra_pnginfo=None):
        import copy
        import json
        import os
        import uuid
        from datetime import datetime, timezone
        from pathlib import Path
        import numpy as np
        from PIL import Image, PngImagePlugin
        import folder_paths

        base = validate_document(load_document(sidecar_json))
        if prompt is not None and not isinstance(prompt, dict):
            raise ValueError("ComfyUI execution prompt must be a JSON object.")
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir,
            images[0].shape[1], images[0].shape[0])
        results = []
        for batch_number, image in enumerate(images):
            name = filename.replace("%batch_num%", str(batch_number))
            file = f"{name}_{counter:05}_.png"
            target = Path(folder) / file
            sidecar = target.with_suffix(".sidecar")
            # Preserve original provenance; only append to processing history.
            doc = copy.deepcopy(base)
            history = doc.setdefault("history", [])
            event = {
                "stage": "image-save",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "output_filename": file,
            }
            if include_current_workflow_in_history:
                if prompt is not None:
                    event["execution_graph"] = prompt
                if isinstance(extra_pnginfo, dict) and "workflow" in extra_pnginfo:
                    event["workflow"] = extra_pnginfo["workflow"]
            history.append(event)
            content = json.dumps(doc, ensure_ascii=False)
            if len(content.encode("utf-8")) > 16 * 1024 * 1024:
                raise ValueError("Lifetime sidecar record exceeds 16 MiB.")
            # Do not overwrite existing images/sidecars during batch saves.
            if target.exists() or sidecar.exists():
                raise FileExistsError("Image or sidecar already exists: " + str(target))
            raw = np.clip(image.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
            output = Image.fromarray(raw)
            metadata = PngImagePlugin.PngInfo()
            if prompt is not None:
                metadata.add_text("prompt", json.dumps(prompt, ensure_ascii=False))
            if extra_pnginfo:
                for key, value in extra_pnginfo.items():
                    if key in {"prompt", "krea_sidecar", "image_sidecar"}:
                        continue
                    metadata.add_text(key, json.dumps(value, ensure_ascii=False))
            metadata.add_itxt("image_sidecar", content, zip=True)
            folder_path = Path(folder)
            temp_png = folder_path / ("." + uuid.uuid4().hex + ".png")
            temp_sidecar = folder_path / ("." + uuid.uuid4().hex + ".sidecar")
            try:
                output.save(temp_png, pnginfo=metadata, compress_level=4)
                temp_sidecar.write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                # If either operation fails, never leave an unpaired output.
                os.replace(temp_png, target)
                try:
                    os.replace(temp_sidecar, sidecar)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
            finally:
                temp_png.unlink(missing_ok=True)
                temp_sidecar.unlink(missing_ok=True)
            results.append({"filename": file, "subfolder": subfolder, "type": "output"})
            counter += 1
        return {"ui": {"images": results}}

NODE_CLASS_MAPPINGS = {
    "ImageUtilsSidecarLoader": ImageUtilsSidecarLoader,
    "ImageUtilsJsonFieldExtractor": ImageUtilsJsonFieldExtractor,
    "ImageUtilsJsonTagChecker": ImageUtilsJsonTagChecker,
    "ImageUtilsConditionalPrompt": ImageUtilsConditionalPrompt,
    "ImageUtilsAppendProcessingEvent": ImageUtilsAppendProcessingEvent,
    "ImageUtilsSaveImageWithSidecar": ImageUtilsSaveImageWithSidecar,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageUtilsSidecarLoader": "Image Utils · Image Sidecar Loader",
    "ImageUtilsJsonFieldExtractor": "Image Utils · JSON Field Extractor",
    "ImageUtilsJsonTagChecker": "Image Utils · JSON Tag Checker",
    "ImageUtilsConditionalPrompt": "Image Utils · Conditional Prompt",
    "ImageUtilsAppendProcessingEvent": "Image Utils · Append Processing Event",
    "ImageUtilsSaveImageWithSidecar": "Image Utils · Save Image + Sidecar (Embedded)",
}
