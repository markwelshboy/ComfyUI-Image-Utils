"""Replace the image in an LC_PIPE while preserving earlier detailers' protection.

LoneCat's lc_protect mask is fingerprinted to the image it was created on.
An external IMAGE-only processing stage (e.g. Impact Pack SEGS) changes the
image and leaves the fingerprint stale. The next LC detailer will otherwise
discard the accumulated mask and start again.

This node only retags an existing, *valid* protection mask for the replacement
image. It neither adds the external stage's mask nor imports any LoneCat code.
"""
from __future__ import annotations


def _lc_image_tag(image):
    """Match lonecatone23/ComfyUI_LC_MaskMaker_nodes/lc_pipe_keys.py:tag exactly.

    In particular, use the same sparse pixel sample, float conversion and
    rounding. A different checksum would make LC's protect_for() reject it.
    """
    if image is None or not hasattr(image, "shape"):
        raise ValueError("MR Pipe Image Replace requires a ComfyUI IMAGE tensor.")
    shape = tuple(image.shape)
    if len(shape) != 4 or shape[0] < 1 or any(dim <= 0 for dim in shape) or shape[3] < 3:
        raise ValueError("Expected a nonempty IMAGE tensor shaped (batch, height, width, channels).")
    try:
        checksum = round(float(image[:, ::37, ::37, :3].float().sum()), 3)
    except (AttributeError, TypeError, ValueError, IndexError) as exc:
        raise ValueError("Could not compute the LoneCat image fingerprint.") from exc
    return (shape, checksum)


class MRPipeImageReplaceProtect:
    """Retag an existing accumulated LC protect mask after pixel-only edits."""

    OUTPUT_NODE = False
    CATEGORY = "Image Utils / MR Lazy Detailers"
    FUNCTION = "replace"
    RETURN_TYPES = ("LC_PIPE",)
    RETURN_NAMES = ("pipe",)
    DESCRIPTION = (
        "Replace a pipe's image after external processing (e.g. SEGS), "
        "preserving the accumulated protection mask from preceding LC/MR "
        "detailers. Requires unchanged image dimensions and spatial alignment. "
        "The external stage contributes NO new protection. Clears cached "
        "SAM3 detections belonging to the old image."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "pipe": ("LC_PIPE", {
                "tooltip": "Original pipe from the previous LC / MR detailer. "
                           "Carries its image, protection mask and sampling settings."
            }),
            "image": ("IMAGE", {
                "tooltip": "New image returned by the external processing stage. "
                           "Must have the same shape and alignment as the old image."
            }),
        }}

    def replace(self, pipe, image):
        if not isinstance(pipe, dict):
            raise ValueError("MR Pipe Image Replace expects an LC_PIPE dictionary.")
        if pipe.get("_type", "LC_PIPE") != "LC_PIPE":
            raise ValueError("MR Pipe Image Replace received a non-LC pipe.")

        old_image = pipe.get("image")
        if old_image is None:
            raise ValueError("LC_PIPE has no original IMAGE to validate protection against.")
        before_tag = _lc_image_tag(old_image)
        after_tag = _lc_image_tag(image)

        if before_tag[0] != after_tag[0]:
            raise ValueError(
                "MR Pipe Image Replace cannot preserve protection after a size, "
                "batch or channel change: old shape "
                f"{before_tag[0]}, new shape {after_tag[0]}. "
                "Keep the SEGS output aligned and at the same resolution."
            )

        result = dict(pipe)  # Do not mutate the incoming pipe or other graph branches.
        result["image"] = image
        result["_type"] = "LC_PIPE"

        protection = pipe.get("lc_protect")
        if protection is not None:
            if not isinstance(protection, dict) or protection.get("mask") is None:
                raise ValueError("LC_PIPE contains an invalid lc_protect entry.")
            if protection.get("tag") != before_tag:
                raise ValueError(
                    "Existing LC protection mask is already stale for the incoming "
                    "pipe image. Refusing to retag a mask whose origin cannot be verified."
                )
            mask = protection["mask"]
            if tuple(getattr(mask, "shape", ())) != before_tag[0][:3]:
                raise ValueError(
                    "Existing lc_protect mask shape does not match the pipe's "
                    "image batch/height/width; cannot safely carry it forward."
                )
            # Preserve exactly the same mask tensor and any extra mask metadata.
            # Only refresh the image-fingerprint portion of lc_protect.
            result["lc_protect"] = {**protection, "tag": after_tag}

        # Old SAM3 finds are no longer trustworthy after external image edits.
        result.pop("lc_found", None)
        return (result,)
