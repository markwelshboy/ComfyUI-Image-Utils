"""Rasterize editable normalized polygons from an image_sidecar JSON document.

Independent of ComfyUI / Torch for testing. A ComfyUI wrapper converts the
Pillow result into a standard float32 MASK [batch, height, width].
"""
from __future__ import annotations

import json
import math
from PIL import Image, ImageDraw

def read_named_mask(sidecar_json, name="anypaint"):
    if not isinstance(name, str) or not name or len(name) > 64:
        raise ValueError("Mask name must be a nonempty string (max 64 characters).")
    try:
        doc = json.loads(sidecar_json or "{}") if isinstance(sidecar_json, str) else sidecar_json
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid JSON supplied to the polygon mask extractor.") from exc
    if not isinstance(doc, dict):
        raise ValueError("Sidecar must be a JSON object.")
    masks = doc.get("masks", {})
    if not isinstance(masks, dict):
        raise ValueError("Sidecar 'masks' must be an object.")
    entry = masks.get(name)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError("Named polygon mask must be an object.")
    if type(entry.get("enabled", True)) is not bool:
        raise ValueError("Mask enabled must be a boolean.")
    prompt = entry.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("Mask prompt must be text.")
    dimensions = entry.get("reference_size")
    if (not isinstance(dimensions, list) or len(dimensions) != 2 or
            any(type(v) is not int or v < 1 for v in dimensions)):
        raise ValueError("Mask reference_size must be [width, height].")
    regions = entry.get("regions", [])
    if not isinstance(regions, list) or len(regions) > 32:
        raise ValueError("Mask regions must be a list of at most 32 polygons.")
    for region in regions:
        if not isinstance(region, dict) or region.get("operation") not in ("add", "subtract"):
            raise ValueError("Each region must use add or subtract.")
        points = region.get("points")
        if not isinstance(points, list) or not 3 <= len(points) <= 200:
            raise ValueError("Every polygon needs 3–200 coordinates.")
        for pair in points:
            if (not isinstance(pair, list) or len(pair) != 2 or
                    any(type(x) not in (int, float) or not math.isfinite(x) or
                        x < 0 or x > 1 for x in pair)):
                raise ValueError("Polygon point coordinates must be normalized floats between 0 and 1.")
    return entry

def make_polygon_image(sidecar_json, mask_name, width, height):
    """Return (PIL image, present, prompt) with white = masked.

    An absent/disabled mask is all black. A different aspect ratio is rejected
    to prevent drawing on a newly cropped/reframed image.
    """
    if (type(width) is not int or type(height) is not int or
            width < 1 or height < 1 or width > 30000 or height > 30000):
        raise ValueError("Image dimensions must be positive finite integers.")
    entry = read_named_mask(sidecar_json, mask_name)
    canvas = Image.new("L", (width, height), 0)
    if entry is None or not entry.get("enabled", True):
        return canvas, False, ""
    regions = entry.get("regions", [])
    if not any(r["operation"] == "add" for r in regions):
        return canvas, False, ""
    source_width, source_height = entry["reference_size"]
    source_ratio = source_width / source_height
    new_ratio = width / height
    if abs(new_ratio / source_ratio - 1) > 0.01:
        raise ValueError("Mask aspect ratio differs from the original image; "
                         "a crop/reframe would misalign the polygon.")
    painter = ImageDraw.Draw(canvas)
    for region in regions:
        points = [(round(x * (width - 1)), round(y * (height - 1)))
                  for x, y in region["points"]]
        painter.polygon(points, fill=255 if region["operation"] == "add" else 0)
    if not canvas.getbbox():
        return canvas, False, ""
    return canvas, True, entry.get("prompt", "")
