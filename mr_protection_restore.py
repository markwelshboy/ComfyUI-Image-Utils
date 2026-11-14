"""Restore a saved protection mask onto the current IMAGE inside an LC_PIPE.

The saved companion contains the mask pixels, not a stale image fingerprint.
When loading a re-encoded PNG, the LC fingerprint must be computed from the
current IMAGE tensor, as expected by the downstream LoneCat detailers.
"""
from __future__ import annotations

from .mr_pipe_image_replace import _lc_image_tag
from .protection_mask import read_protection_file, protection_signature


class MRLoadProtectionIntoPipe:
    """Read <image>.protection_mask and attach it to IMAGE in an LC_PIPE."""

    CATEGORY = "Image Utils / MR Lazy Detailers"
    FUNCTION = "load"
    OUTPUT_NODE = False
    RETURN_TYPES = ("LC_PIPE", "MASK", "BOOLEAN")
    RETURN_NAMES = ("pipe", "protection_mask", "found")
    DESCRIPTION = (
        "Restore the lossless protection mask companion of an input image into "
        "an LC_PIPE, tagged for the current loaded image. Use after loading an "
        "image with Sequential Image Loader. The optional pipe retains model, "
        "VAE, sampler, prompts and other settings; with no pipe, the result "
        "contains only image and protection. Old SAM3 finds are discarded."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image_path": ("STRING", {
                "forceInput": True,
                "tooltip": "Full image filename from Sequential Image Loader. "
                           "Reads a sibling <image>.protection_mask file."
            }),
            "image": ("IMAGE", {
                "tooltip": "Current loaded IMAGE; used to calculate the current "
                           "LoneCat protection fingerprint."
            }),
            "missing_policy": (["error", "empty"], {
                "default": "error",
                "tooltip": "Error if the protection file is missing (safest), or "
                           "continue with an empty mask and found=false."
            }),
        }, "optional": {
            "pipe": ("LC_PIPE", {
                "tooltip": "Existing LC pipe to preserve model/sampler settings. "
                           "Replaces its image and protection with loaded values."
            }),
        }}

    @classmethod
    def IS_CHANGED(cls, image_path, image=None, missing_policy="error", pipe=None):
        return protection_signature(image_path)

    def load(self, image_path, image, missing_policy="error", pipe=None):
        import torch
        tag = _lc_image_tag(image)
        batch, height, width, _channels = tag[0]
        if batch != 1:
            raise ValueError(
                "A .protection_mask file belongs to one saved image. "
                "Load files one at a time (IMAGE batch size must be 1)."
            )
        if missing_policy not in ("error", "empty"):
            raise ValueError("Invalid missing protection policy.")
        if pipe is not None and not isinstance(pipe, dict):
            raise ValueError("Expected optional pipe to be an LC_PIPE dictionary.")
        if pipe is not None and pipe.get("_type", "LC_PIPE") != "LC_PIPE":
            raise ValueError("Expected an LC_PIPE (not another pipe type).")
        if pipe is not None and pipe.get("image") is not None:
            old = _lc_image_tag(pipe["image"])
            if old[0] != tag[0]:
                raise ValueError(
                    "Existing pipe IMAGE dimensions differ from the restored image. "
                    "Protection must be spatially aligned."
                )
        try:
            array = read_protection_file(
                image_path, expected_shape=(height, width))
            found = True
        except FileNotFoundError:
            if missing_policy != "empty":
                raise
            array, found = None, False

        result = dict(pipe) if pipe is not None else {}
        result["_type"] = "LC_PIPE"
        result["image"] = image
        result.pop("lc_found", None)

        if found:
            # A CPU float32 tensor, exactly the saved soft mask, with B=1.
            mask = torch.from_numpy(array[None, ...].copy())
            result["lc_protect"] = {"mask": mask, "tag": tag}
        else:
            result.pop("lc_protect", None)
            mask = torch.zeros((1, height, width), dtype=torch.float32)

        return result, mask, found
