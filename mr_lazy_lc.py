"""Non-output adapters for LoneCat MaskMaker's pipe detailers.

The original LoneCat nodes remain untouched and registered under their original
IDs. Resolve the upstream class when ComfyUI requests INPUT_TYPES (or execution)
rather than at module import time, so custom-node load order is irrelevant.
"""
from __future__ import annotations

EXPECTED_RETURNS = ("LC_PIPE", "IMAGE", "MASK")


def _upstream(node_id):
    try:
        import nodes  # ComfyUI node registry; available after custom-node loading
    except ImportError as exc:
        raise RuntimeError(
            "MR lazy detailers require ComfyUI and the installed LC MaskMaker pack."
        ) from exc
    candidate = nodes.NODE_CLASS_MAPPINGS.get(node_id)
    if candidate is None:
        raise RuntimeError(
            f"Missing LoneCat node {node_id}. Install/update "
            "lonecatone23/ComfyUI_LC_MaskMaker_nodes and restart ComfyUI."
        )
    if tuple(getattr(candidate, "RETURN_TYPES", ())) != EXPECTED_RETURNS:
        raise RuntimeError(
            f"LoneCat {node_id} changed RETURN_TYPES; MR adapter expected "
            f"{EXPECTED_RETURNS}. Update the adapter before using it."
        )
    if not callable(getattr(candidate, "run", None)):
        raise RuntimeError(f"LoneCat {node_id} no longer exposes run().")
    schema = candidate.INPUT_TYPES()
    if "pipe" not in schema.get("required", {}):
        raise RuntimeError(
            f"LoneCat {node_id} no longer accepts a required LC_PIPE input."
        )
    return candidate


class _MRLazyLCPipeAdapter:
    """Delegate execution to the unmodified LoneCat node only if requested.

    A distinct OUTPUT_NODE=False ComfyUI node ID is essential: merely wrapping
    a standalone original OUTPUT_NODE=True instance in a Lazy Switch would
    not prevent it from running as an independent execution root.
    """

    ORIGINAL_NODE = ""
    OUTPUT_NODE = False
    CATEGORY = "Image Utils / MR Lazy Detailers"
    FUNCTION = "run"
    RETURN_TYPES = EXPECTED_RETURNS
    RETURN_NAMES = ("pipe", "image", "mask")
    DESCRIPTION = (
        "Lazy-schedulable LoneCat pipe detailer. Connect its pipe output to "
        "KJ Lazy Switch (on_false), and the incoming pipe to on_true. "
        "The original LoneCat nodes are unchanged."
    )

    @classmethod
    def INPUT_TYPES(cls):
        # ComfyUI normally builds schemas after registering all custom packs.
        # A minimal schema on missing dependency allows other Image Utils nodes
        # to keep loading; run() then emits an actionable error.
        try:
            return _upstream(cls.ORIGINAL_NODE).INPUT_TYPES()
        except RuntimeError:
            return {"required": {"pipe": ("LC_PIPE",)}, "optional": {"image": ("IMAGE",)}}

    @classmethod
    def VALIDATE_INPUTS(cls, sam3_model=None):
        upstream = _upstream(cls.ORIGINAL_NODE)
        validator = getattr(upstream, "VALIDATE_INPUTS", None)
        return validator(sam3_model=sam3_model) if validator else True

    def run(self, **kwargs):
        upstream = _upstream(self.ORIGINAL_NODE)
        if getattr(self, "_upstream_class", None) is not upstream:
            self._upstream_instance = upstream()
            self._upstream_class = upstream
        response = self._upstream_instance.run(**kwargs)
        # LoneCat's custom frontend understands lc_inpaint. Standard ComfyUI
        # IMAGE preview handling expects images; provide both keys so the MR
        # node still shows a result with only the stock frontend installed.
        if isinstance(response, dict) and isinstance(response.get("ui"), dict):
            ui = dict(response["ui"])
            if "images" not in ui and isinstance(ui.get("lc_inpaint"), list):
                after = ui["lc_inpaint"]
                if after:
                    ui["images"] = after[-1:]
            return {**response, "ui": ui}
        return response


class MRLazySmartDetailerPipe(_MRLazyLCPipeAdapter):
    ORIGINAL_NODE = "LCSmartInpaintPipe"


class MRLazyCharacterDetailerPipe(_MRLazyLCPipeAdapter):
    ORIGINAL_NODE = "LCCharacterDetailerPipe"
