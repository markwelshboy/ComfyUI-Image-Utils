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
        }, "optional": {
            "protection_mask": ("MASK", {
                "tooltip": "Optional accumulated protection mask from LC Pipe Out. "
                           "Saves one lossless <image>.protection_mask companion "
                           "beside each PNG and .sidecar."
            }),
        }, "hidden": {
            "prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO",
        }}

    def save_images(self, images, sidecar_json, filename_prefix="ImageUtils",
                    include_current_workflow_in_history=True,
                    prompt=None, extra_pnginfo=None, protection_mask=None):
        import copy
        import json
        import os
        import uuid
        from datetime import datetime, timezone
        from pathlib import Path
        import numpy as np
        from PIL import Image, PngImagePlugin
        import folder_paths
        from .protection_mask import masks_for_save, write_protection_file

        # Validate the entire mask batch before saving any output files.
        # One exact-size mask is persisted per saved image; no broadcasting.
        prepared_masks = (masks_for_save(protection_mask, tuple(images.shape))
                          if protection_mask is not None else None)
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
            mask_target = target.with_suffix(".protection_mask") if prepared_masks is not None else None
            # Preserve original provenance; only append to processing history.
            doc = copy.deepcopy(base)
            history = doc.setdefault("history", [])
            event = {
                "stage": "image-save",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "output_filename": file,
            }
            if mask_target is not None:
                event["protection_mask_file"] = mask_target.name
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
            if target.exists() or sidecar.exists() or (mask_target is not None and mask_target.exists()):
                raise FileExistsError("Image, sidecar or protection mask already exists: " + str(target))
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
            temp_mask = folder_path / ("." + uuid.uuid4().hex + ".protection_mask") if mask_target else None
            staged = [(temp_png, target), (temp_sidecar, sidecar)]
            if mask_target is not None:
                staged.append((temp_mask, mask_target))
            committed = []
            try:
                output.save(temp_png, pnginfo=metadata, compress_level=4)
                temp_sidecar.write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                if mask_target is not None:
                    write_protection_file(temp_mask, prepared_masks[batch_number])
                # Roll back all companions for this frame on any failure.
                for temporary, destination in staged:
                    os.replace(temporary, destination)
                    committed.append(destination)
            except Exception:
                for destination in reversed(committed):
                    destination.unlink(missing_ok=True)
                raise
            finally:
                for temporary, _ in staged:
                    temporary.unlink(missing_ok=True)
            results.append({"filename": file, "subfolder": subfolder, "type": "output"})
            counter += 1
        return {"ui": {"images": results}}


class ImageUtilsLazyImageBypass:
    """Skip an expensive detailer branch when bypass is True.

    Crucially BOTH image inputs are lazy: ComfyUI only requests the selected
    image branch. Unlike a regular switch, the unselected branch does not
    need to execute unless some other output node independently requests it.
    """
    CATEGORY = CATEGORY
    FUNCTION = "route"
    RETURN_TYPES = ("IMAGE", "BOOLEAN")
    RETURN_NAMES = ("image", "bypassed")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "bypass": ("BOOLEAN", {"forceInput": True}),
            "passthrough_image": ("IMAGE", {"lazy": True}),
            "processed_image": ("IMAGE", {"lazy": True}),
        }}

    def check_lazy_status(self, bypass, passthrough_image=None, processed_image=None):
        if bypass:
            return ["passthrough_image"] if passthrough_image is None else []
        return ["processed_image"] if processed_image is None else []

    def route(self, bypass, passthrough_image=None, processed_image=None):
        image = passthrough_image if bypass else processed_image
        if image is None:
            raise ValueError(
                "Lazy Image Bypass did not receive the selected IMAGE branch. "
                "Check that the corresponding Get/Set or physical link is connected."
            )
        return image, bool(bypass)


class ImageUtilsTagPromptSelector:
    """Choose a single prompt based on tags, with explicit precedence and diagnostics."""
    CATEGORY = CATEGORY
    FUNCTION = "select"
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("selected_prompt", "matched_tag", "used_default", "matched_count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sidecar_json": ("STRING", {"forceInput": True}),
            "default_prompt": ("STRING", {"default": "", "multiline": True}),
            "mapping_json": ("STRING", {
                "default": (
                    '{\n'
                    '  "eyes-closed": "Natural closed eyelids, detailed eyelashes, no visible iris",\n'
                    '  "eyes-half-closed": "Natural half-closed eyelids, partial iris, delicate lashes",\n'
                    '  "bright-green-eyes": "Bright green irises, detailed pupils, natural lashes"\n'
                    '}'
                ),
                "multiline": True,
            }),
            "priority_csv": ("STRING", {
                "default": "eyes-closed, eyes-half-closed, bright-green-eyes",
                "tooltip": "First matching tag wins. Unlisted mapping keys follow JSON insertion order."
            }),
            "strict_single_match": ("BOOLEAN", {
                "default": False,
                "tooltip": "Raise an error instead of using priority when multiple mapped tags match."
            }),
        }}

    def select(self, sidecar_json, default_prompt, mapping_json,
               priority_csv="", strict_single_match=False):
        from .routing import select_tag_prompt
        return select_tag_prompt(sidecar_json, default_prompt, mapping_json,
                                 priority_csv, strict_single_match)


class ImageUtilsInlineImagePreview:
    """Non-output IMAGE preview which runs only when its IMAGE output is consumed."""
    CATEGORY = CATEGORY
    FUNCTION = "preview"
    OUTPUT_NODE = False
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "enabled": ("BOOLEAN", {"default": True}),
            "max_preview_edge": ("INT", {"default": 1024, "min": 128, "max": 4096, "step": 64}),
            "batch_frames": ("INT", {"default": 1, "min": 1, "max": 8}),
        }}

    def preview(self, image, enabled=True, max_preview_edge=1024, batch_frames=1):
        if not enabled:
            return {"ui": {"images": []}, "result": (image,)}
        from .preview import save_inline_previews
        images = save_inline_previews(
            [("image", image, False)], max_preview_edge, batch_frames)
        return {"ui": {"images": images}, "result": (image,)}


class ImageUtilsInlineCropPreview:
    """Inline crop/mask debug preview, passing the main IMAGE through unchanged.

    The main image should be the *processed* detailer output, not its incoming
    original IMAGE, so that preview work stays inside the lazy detailer branch.
    """
    CATEGORY = CATEGORY
    FUNCTION = "preview"
    OUTPUT_NODE = False
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "enabled": ("BOOLEAN", {"default": True}),
            "max_preview_edge": ("INT", {"default": 1024, "min": 128, "max": 4096, "step": 64}),
            "batch_frames": ("INT", {"default": 1, "min": 1, "max": 8}),
        }, "optional": {
            "crop_image": ("IMAGE",),
            "crop_mask": ("MASK",),
        }}

    def preview(self, image, enabled=True, max_preview_edge=1024, batch_frames=1,
                crop_image=None, crop_mask=None):
        if not enabled:
            return {"ui": {"images": []}, "result": (image,)}
        from .preview import save_inline_previews
        previews = []
        if crop_image is not None:
            previews.append(("crop", crop_image, False))
        if crop_mask is not None:
            previews.append(("mask", crop_mask, True))
        if not previews:
            previews.append(("image", image, False))
        images = save_inline_previews(previews, max_preview_edge, batch_frames)
        return {"ui": {"images": images}, "result": (image,)}


NODE_CLASS_MAPPINGS = {
    "ImageUtilsSidecarLoader": ImageUtilsSidecarLoader,
    "ImageUtilsJsonFieldExtractor": ImageUtilsJsonFieldExtractor,
    "ImageUtilsJsonTagChecker": ImageUtilsJsonTagChecker,
    "ImageUtilsConditionalPrompt": ImageUtilsConditionalPrompt,
    "ImageUtilsAppendProcessingEvent": ImageUtilsAppendProcessingEvent,
    "ImageUtilsSaveImageWithSidecar": ImageUtilsSaveImageWithSidecar,
    "ImageUtilsLazyImageBypass": ImageUtilsLazyImageBypass,
    "ImageUtilsTagPromptSelector": ImageUtilsTagPromptSelector,
    "ImageUtilsInlineImagePreview": ImageUtilsInlineImagePreview,
    "ImageUtilsInlineCropPreview": ImageUtilsInlineCropPreview,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageUtilsSidecarLoader": "Image Utils · Image Sidecar Loader",
    "ImageUtilsJsonFieldExtractor": "Image Utils · JSON Field Extractor",
    "ImageUtilsJsonTagChecker": "Image Utils · JSON Tag Checker",
    "ImageUtilsConditionalPrompt": "Image Utils · Conditional Prompt",
    "ImageUtilsAppendProcessingEvent": "Image Utils · Append Processing Event",
    "ImageUtilsSaveImageWithSidecar": "Image Utils · Save Image + Sidecar (Embedded)",
    "ImageUtilsLazyImageBypass": "Image Utils · Lazy Image Bypass",
    "ImageUtilsTagPromptSelector": "Image Utils · Tag Prompt Selector",
    "ImageUtilsInlineImagePreview": "Image Utils · Inline Image Preview",
    "ImageUtilsInlineCropPreview": "Image Utils · Inline Crop Preview",
}


# Optional LoneCat-compatible MR nodes. Upstream classes are resolved after
# ComfyUI finishes loading its custom-node registry, never at import time.
from .mr_lazy_lc import MRLazySmartDetailerPipe, MRLazyCharacterDetailerPipe
from .mr_diagnostics import MRInlineVRAMClear, MRConditionalPreviewSink
from .mr_pipe_image_replace import MRPipeImageReplaceProtect
from .mr_protection_restore import MRLoadProtectionIntoPipe

NODE_CLASS_MAPPINGS.update({
    "ImageUtilsMRLazySmartDetailerPipe": MRLazySmartDetailerPipe,
    "ImageUtilsMRLazyCharacterDetailerPipe": MRLazyCharacterDetailerPipe,
    "ImageUtilsMRInlineVRAMClear": MRInlineVRAMClear,
    "ImageUtilsMRConditionalPreviewSink": MRConditionalPreviewSink,
    "ImageUtilsMRPipeImageReplaceProtect": MRPipeImageReplaceProtect,
    "ImageUtilsMRLoadProtectionIntoPipe": MRLoadProtectionIntoPipe,
})
NODE_DISPLAY_NAME_MAPPINGS.update({
    "ImageUtilsMRLazySmartDetailerPipe": "MR Lazy Smart Detailer (pipe)",
    "ImageUtilsMRLazyCharacterDetailerPipe": "MR Lazy Character Detailer (pipe)",
    "ImageUtilsMRInlineVRAMClear": "MR VRAM Cache Clear (Inline)",
    "ImageUtilsMRConditionalPreviewSink": "MR Conditional Preview Sink",
    "ImageUtilsMRPipeImageReplaceProtect": "MR Pipe Image Replace (Preserve Protection)",
    "ImageUtilsMRLoadProtectionIntoPipe": "MR Load Protection Into Pipe",
})
WEB_DIRECTORY = "./web"
