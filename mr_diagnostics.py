"""Optional inline VRAM cleanup and conditional multi-input diagnostic sink.

The sink is an intentional OUTPUT_NODE: it executes every queued item to show
SKIPPED or SELECTED, but its connected preview inputs are lazy and are only
requested when the corresponding detailer was selected. It must share the
exact same bypass Boolean as the downstream KJ Lazy Switch.
"""
from __future__ import annotations

PREVIEW_INPUTS = ("image_1", "image_2", "mask_1", "mask_2")


class MRInlineVRAMClear:
    """LoneCat-compatible passthrough cleanup, without output-root scheduling."""

    OUTPUT_NODE = False
    FUNCTION = "clear"
    CATEGORY = "Image Utils / MR Lazy Detailers"
    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("any",)
    DESCRIPTION = (
        "Pass-through cleanup on a selected detailer branch. Unlike "
        "LC VRAM Cache Clear, this node is NOT an independent output: "
        "place it before the processed-pipe input to KJ Lazy Switch."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"any": ("*",)}}

    def clear(self, any):
        import gc
        try:
            import comfy.model_management as mm
            mm.cleanup_models()
            mm.soft_empty_cache()
        except Exception:
            pass
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except (ImportError, RuntimeError):
            pass
        return (any,)


class MRConditionalPreviewSink:
    """Output-root with LAZY preview sockets; bypass avoids pulling the branch.

    The status indicates which path was selected, not whether the detailer was
    freshly recomputed versus served from ComfyUI's execution cache.
    """

    OUTPUT_NODE = True
    FUNCTION = "sink"
    CATEGORY = "Image Utils / MR Lazy Detailers"
    RETURN_TYPES = ()
    DESCRIPTION = (
        "Conditional preview collector with a SKIPPED / SELECTED status lamp. "
        "Connect bypass to the SAME Boolean as KJ Lazy Switch; when bypassed, "
        "no image/mask input is requested. The original LC detailer and "
        "LC Preview Mask must not be independent output roots."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bypass": ("BOOLEAN", {"forceInput": True}),
                "stage": ("STRING", {"default": "Face"}),
                "max_preview_edge": ("INT", {"default": 1024, "min": 128, "max": 4096, "step": 64}),
                "batch_frames": ("INT", {"default": 1, "min": 1, "max": 8}),
            },
            "optional": {
                "image_1": ("IMAGE", {"lazy": True}),
                "image_2": ("IMAGE", {"lazy": True}),
                "mask_1": ("MASK", {"lazy": True}),
                "mask_2": ("MASK", {"lazy": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID", "dynprompt": "DYNPROMPT"},
        }

    @staticmethod
    def _connected(unique_id=None, dynprompt=None):
        if unique_id is None or dynprompt is None:
            return PREVIEW_INPUTS
        try:
            node = dynprompt.get_node(str(unique_id))
            connected = node.get("inputs", {})
            return tuple(k for k in PREVIEW_INPUTS if k in connected)
        except (KeyError, ValueError, TypeError, AttributeError):
            # Safe fallback: request only those inputs which ComfyUI knows are
            # connected; unconnected optional sockets are ignored by executor.
            return PREVIEW_INPUTS

    def check_lazy_status(
        self, bypass, stage="Face", max_preview_edge=1024, batch_frames=1,
        image_1=None, image_2=None, mask_1=None, mask_2=None,
        unique_id=None, dynprompt=None,
    ):
        if bypass:
            return []
        values = {
            "image_1": image_1,
            "image_2": image_2,
            "mask_1": mask_1,
            "mask_2": mask_2,
        }
        return [
            key for key in self._connected(unique_id, dynprompt)
            if values[key] is None
        ]

    def sink(
        self, bypass, stage="Face", max_preview_edge=1024, batch_frames=1,
        image_1=None, image_2=None, mask_1=None, mask_2=None,
        unique_id=None, dynprompt=None,
    ):
        if bypass:
            return {"ui": {
                "images": [],
                "mr_preview_status": [{"stage": str(stage), "state": "skipped"}],
            }, "result": ()}
        sources = [
            ("Image 1", image_1, False),
            ("Image 2", image_2, False),
            ("Mask 1", mask_1, True),
            ("Mask 2", mask_2, True),
        ]
        sources = [item for item in sources if item[1] is not None]
        from .preview import save_inline_previews
        images = save_inline_previews(sources, max_preview_edge, batch_frames) if sources else []
        state = "selected" if images else "no-previews"
        return {"ui": {
            "images": images,
            "mr_preview_status": [{"stage": str(stage), "state": state}],
        }, "result": ()}
