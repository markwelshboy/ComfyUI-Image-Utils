"""Lossless ComfyUI protection-mask companion files.

For a saved `photo.png`, the optional mask lives at `photo.protection_mask`.
The extension is deliberate: the data is *not* a PNG or JSON file, but a
compressed NumPy archive (NPZ) containing a float32 mask and format version.
Saving raw 32-bit values retains LoneCat's soft edges without quantization.

One file represents exactly one saved image (one H x W mask). Batches are
split into one companion per output image by the Image Utils save node.
"""
from __future__ import annotations

from pathlib import Path

VERSION = 1
MAX_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 8192 * 8192


def protection_candidates(image_path):
    """Prefer an unambiguous whole-image filename, like sidecar.py does."""
    path = Path(image_path).expanduser()
    return (Path(str(path) + ".protection_mask"),
            path.with_suffix(".protection_mask"))


def protection_for_image(image_path):
    """Return an existing companion (full-name first), else the stem path."""
    full, stem = protection_candidates(image_path)
    return full if full.is_file() else stem


def protection_signature(image_path):
    """ComfyUI IS_CHANGED hook: invalidates cache on mask add/edit/delete."""
    path = protection_for_image(image_path)
    try:
        st = path.stat()
        return (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(path), None, None)


def _numpy_mask(data, *, expected_shape=None):
    """Validate and copy a single float mask to CPU float32 without clamping."""
    import numpy as np
    if hasattr(data, "detach"):
        data = data.detach().cpu().numpy()
    arr = np.asarray(data)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        raise ValueError("Each protection mask must have shape (height, width).")
    if arr.size == 0 or arr.size > MAX_PIXELS:
        raise ValueError("Protection mask dimensions are empty or exceed 8192x8192 pixels.")
    if expected_shape is not None and tuple(arr.shape) != tuple(expected_shape):
        raise ValueError(
            f"Protection mask size {tuple(arr.shape)} does not match image {tuple(expected_shape)}."
        )
    if arr.dtype.kind not in ("f", "i", "u"):
        raise ValueError("Protection mask must contain numeric data.")
    arr = np.array(arr, dtype=np.float32, copy=True)
    if not np.isfinite(arr).all():
        raise ValueError("Protection mask contains NaN or Infinity.")
    if np.any(arr < 0) or np.any(arr > 1):
        raise ValueError("Protection mask values must be in [0, 1].")
    return arr


def masks_for_save(mask, image_shape):
    """Validate one mask per image, returning (B,H,W) float32, or None."""
    import numpy as np
    if mask is None:
        return None
    if len(image_shape) != 4:
        raise ValueError("Images must have shape (batch, height, width, channels).")
    batch, height, width, _channels = tuple(image_shape)
    if hasattr(mask, "detach"):
        mask = mask.detach().cpu().numpy()
    raw = np.asarray(mask)
    if raw.ndim == 2:
        raw = raw[None, ...]
    if raw.ndim != 3 or raw.shape != (batch, height, width):
        raise ValueError(
            "Protection mask must be (batch, height, width) matching saved images: "
            f"expected {(batch, height, width)}, got {tuple(raw.shape)}."
        )
    return np.stack([
        _numpy_mask(raw[index], expected_shape=(height, width))
        for index in range(batch)
    ], axis=0)


def write_protection_file(filename, mask):
    """Write a single-image NPZ archive to an exact path (no extension added)."""
    import numpy as np
    arr = _numpy_mask(mask)
    with Path(filename).open("xb") as stream:
        np.savez_compressed(stream,
                            mask=arr,
                            version=np.array(VERSION, dtype=np.int16))


def read_protection_file(image_path, *, expected_shape=None):
    """Read and validate the companion file for an image. Missing is an error."""
    import numpy as np
    import zipfile
    path = protection_for_image(image_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No protection mask beside {image_path}; expected {path}. "
            "Connect a protection_mask input to Save Image + Sidecar first."
        )
    if path.stat().st_size > MAX_COMPRESSED_BYTES:
        raise ValueError("Protection mask companion exceeds 256 MiB.")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if {x.filename for x in members} != {"mask.npy", "version.npy"}:
                raise ValueError("Invalid protection mask archive entries.")
            if sum(x.file_size for x in members) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Protection mask archive expands beyond 512 MiB.")
            if any(x.file_size > MAX_UNCOMPRESSED_BYTES for x in members):
                raise ValueError("Oversized protection mask archive member.")
        with np.load(path, allow_pickle=False) as payload:
            version = payload["version"]
            if version.shape != () or int(version) != VERSION:
                raise ValueError("Unsupported protection mask file version.")
            data = _numpy_mask(payload["mask"], expected_shape=expected_shape)
        return data
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        raise ValueError(f"Invalid protection mask file {path}: {error}") from error
