"""Generic ComfyUI image-sidecar and conditional control nodes.

A standard ComfyUI STRING connection accepts shootthesound's Sequential Image
Loader's 'file_path' output. Everything runs against the Python backend's
filesystem, including when the backend is hosted on a pod.

This package deliberately has no frontend-JavaScript/socket monkeypatching.
Its output types are always stable when the JSON schema changes.
"""
from .sidecar import (
    read_sidecar, typed_field, has_tag, conditional_prompt, sidecar_signature
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


NODE_CLASS_MAPPINGS = {
    "ImageUtilsSidecarLoader": ImageUtilsSidecarLoader,
    "ImageUtilsJsonFieldExtractor": ImageUtilsJsonFieldExtractor,
    "ImageUtilsJsonTagChecker": ImageUtilsJsonTagChecker,
    "ImageUtilsConditionalPrompt": ImageUtilsConditionalPrompt,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageUtilsSidecarLoader": "Image Utils · Image Sidecar Loader",
    "ImageUtilsJsonFieldExtractor": "Image Utils · JSON Field Extractor",
    "ImageUtilsJsonTagChecker": "Image Utils · JSON Tag Checker",
    "ImageUtilsConditionalPrompt": "Image Utils · Conditional Prompt",
}
