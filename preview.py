"""Temp image previews for non-output, dependency-driven passthrough nodes.

These helpers are imported only when an inline preview actually executes.
"""
from __future__ import annotations

import uuid
from pathlib import Path


def save_inline_previews(inputs, max_preview_edge=1024, batch_frames=1):
    """Return standard ComfyUI UI image descriptors, never an output node.

    inputs: iterable of (label, image_tensor, is_mask).
    Only preview copies are resized or encoded. Original IMAGE and MASK tensors
    are returned unchanged by their passthrough nodes.
    """
    import numpy as np
    from PIL import Image
    import folder_paths

    edge = int(max_preview_edge)
    count = int(batch_frames)
    if not (128 <= edge <= 4096):
        raise ValueError("Preview maximum edge must be between 128 and 4096.")
    if not (1 <= count <= 8):
        raise ValueError("Preview batch frames must be between 1 and 8.")

    tmp = Path(folder_paths.get_temp_directory())
    tmp.mkdir(parents=True, exist_ok=True)
    results = []
    for label, tensor, is_mask in inputs:
        if tensor is None:
            continue
        # ComfyUI images are BHWC and masks are BHW (or sometimes HW).
        data = tensor.detach().cpu().numpy() if hasattr(tensor, "detach") else np.asarray(tensor)
        if is_mask:
            if data.ndim == 2:
                data = data[None, :, :]
            if data.ndim != 3:
                raise ValueError("Preview crop mask should have shape BHW or HW.")
        elif data.ndim != 4 or data.shape[-1] not in (1, 3, 4):
            raise ValueError("Preview image must have shape BHWC, with 1/3/4 channels.")

        for index in range(min(len(data), count)):
            frame = np.uint8(np.clip(data[index].astype(np.float32) * 255.0, 0, 255))
            if is_mask:
                image = Image.fromarray(frame, mode="L")
            elif frame.shape[-1] == 1:
                image = Image.fromarray(frame[..., 0], mode="L")
            else:
                image = Image.fromarray(frame)
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            filename = "image_utils_inline_" + str(label) + "_" + uuid.uuid4().hex + ".png"
            # Keep previews temporary; ComfyUI manages its temp directory.
            image.save(tmp / filename, format="PNG", compress_level=1)
            results.append({"filename": filename, "subfolder": "", "type": "temp"})
    return results
