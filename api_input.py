"""Stateless image input driven by an external ComfyUI API controller.

Drop-in socket-compatible replacement for the shootthesound Sequential Image
Loader. Instead of an index/directory browser, Image-Compare assigns the exact
uploaded filename for *each prompt*, so retries never advance a hidden cursor.
"""
from pathlib import Path


class MRImageCompareInput:
    CATEGORY = "Image Utils / Sidecars"
    FUNCTION = "load"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "mask", "filename", "index", "total", "file_path")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image_name": ("STRING", {
                "default": "", "multiline": False,
                "tooltip": "Path relative to ComfyUI's input directory. Populated automatically by Image-Compare.",
            })
        }}

    @classmethod
    def IS_CHANGED(cls, image_name):
        try:
            import folder_paths
            file = cls.resolve(image_name, folder_paths.get_input_directory())
            stat = file.stat()
            return (str(file), stat.st_mtime_ns, stat.st_size)
        except (ValueError, OSError):
            return image_name

    @staticmethod
    def resolve(image_name, input_dir):
        if not isinstance(image_name, str) or not image_name or "\\" in image_name or "\0" in image_name:
            raise ValueError("Enter a path relative to ComfyUI's input directory.")
        root = Path(input_dir).resolve()
        candidate = (root / image_name).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("Image-Compare input not found under ComfyUI input: " + image_name)
        if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
            raise ValueError("Unsupported image format: " + candidate.suffix)
        return candidate

    def load(self, image_name):
        import numpy as np
        import torch
        from PIL import Image, ImageOps
        import folder_paths

        path = self.resolve(image_name, folder_paths.get_input_directory())
        with Image.open(path) as image:
            fixed = ImageOps.exif_transpose(image)
            pixels = np.asarray(fixed.convert("RGB"), dtype=np.float32) / 255.0
            if "A" in fixed.getbands():
                alpha = np.asarray(fixed.getchannel("A"), dtype=np.float32) / 255.0
                mask = torch.from_numpy((1.0 - alpha).copy()).unsqueeze(0)
            else:
                mask = torch.zeros((1, fixed.height, fixed.width), dtype=torch.float32)
        tensor = torch.from_numpy(pixels.copy()).unsqueeze(0)
        return {"ui": {"image_compare": {"path": str(path), "filename": path.name}},
                "result": (tensor, mask, path.name, 0, 1, str(path))}

# ComfyUI's core /upload/image is for images. Companion files (.sidecar and
# .protection_mask) use a deliberately restricted byte-upload endpoint, rather
# than depending on the image asset/thumbnail pipeline accepting JSON/binary.
try:
    import os
    import re
    import tempfile
    from server import PromptServer
    from aiohttp import web

    @PromptServer.instance.routes.post("/image_compare/upload_companion")
    async def image_compare_upload_companion(request):
        if request.content_length is None or request.content_length > 17 * 1024 * 1024:
            return web.json_response({"error": "Companion exceeds size limit."}, status=413)
        fields = await request.post()
        uploaded = fields.get("file")
        subfolder = fields.get("subfolder")
        name = getattr(uploaded, "filename", None)
        if (not isinstance(subfolder, str) or
                not re.fullmatch(r"image-compare/[a-f0-9]{32}(?:/[A-Za-z0-9 _.~-]+)*", subfolder) or
                not isinstance(name, str) or not name or "/" in name or "\\" in name or
                name.startswith(".") or not name.endswith((".sidecar", ".protection_mask"))):
            return web.json_response({"error": "Invalid Image-Compare companion destination."}, status=400)
        import folder_paths
        root = Path(folder_paths.get_input_directory()).resolve()
        folder = (root / subfolder).resolve()
        target = (folder / name).resolve()
        if not target.is_relative_to(root):
            return web.json_response({"error": "Companion path leaves ComfyUI input."}, status=403)
        folder.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".mr-upload-", delete=False) as stream:
                temp = Path(stream.name)
                amount = 0
                while True:
                    block = uploaded.file.read(1024 * 1024)
                    if not block:
                        break
                    amount += len(block)
                    if amount > 16 * 1024 * 1024:
                        raise ValueError("Companion exceeds 16 MiB.")
                    stream.write(block)
            if target.exists():
                # Retry is safe only if the content is the same.
                if target.read_bytes() != temp.read_bytes():
                    return web.json_response({"error": "Companion exists with different content."}, status=409)
            else:
                os.link(temp, target)
            return web.json_response({"name": name, "subfolder": subfolder, "type": "input"})
        except (OSError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
except ImportError:
    # Importing this module in ordinary Python unit tests is supported.
    pass
