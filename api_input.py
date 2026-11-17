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
