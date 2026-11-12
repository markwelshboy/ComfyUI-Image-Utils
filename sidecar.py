"""JSON sidecars beside images, resolved using the original full path.

Default: /workspace/input/image with spaces.png
         /workspace/input/image with spaces.sidecar

When two images share one stem (foo.png and foo.jpg), exporters may write
foo.png.sidecar and foo.jpg.sidecar instead. These are preferred if present.

No ComfyUI imports: this module can be used and tested by ordinary Python.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

MAX_SIDECAR_BYTES = 1024 * 1024
DEFAULT_DOC = {"version": 1, "tags": [], "controls": {}, "prompts": {}}


def sidecar_candidates(image_path):
    """Return the preferred unambiguous name, then the usual stem.sidecar."""
    image = Path(image_path).expanduser()
    return (Path(str(image) + ".sidecar"), image.with_suffix(".sidecar"))


def sidecar_for_image(image_path):
    """Return the existing .sidecar path; otherwise the conventional path."""
    preferred, conventional = sidecar_candidates(image_path)
    if preferred.is_file():
        return preferred
    return conventional


def validate_document(data):
    if not isinstance(data, dict):
        raise ValueError("Sidecar root must be a JSON object.")
    if "version" in data and data["version"] != 1:
        raise ValueError("Unsupported sidecar version: " + str(data["version"]))
    if "tags" in data:
        if not isinstance(data["tags"], list) or not all(isinstance(x, str) for x in data["tags"]):
            raise ValueError("Sidecar 'tags' must be a list of strings.")
    for key in ("controls", "prompts"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError("Sidecar '" + key + "' must be an object.")
    return data


def read_sidecar(image_path):
    """(JSON dictionary, found, selected absolute sidecar path).

    Missing files are not errors; malformed JSON is an actionable error.
    """
    chosen = sidecar_for_image(image_path)
    if not chosen.is_file():
        return dict(version=1, tags=[], controls={}, prompts={}), False, str(chosen.absolute())
    if chosen.stat().st_size > MAX_SIDECAR_BYTES:
        raise ValueError("Sidecar exceeds 1 MiB: " + str(chosen))
    try:
        with chosen.open("r", encoding="utf-8-sig") as stream:
            document = json.load(stream)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid sidecar JSON (" + str(chosen) + "): " + str(error)) from error
    return validate_document(document), True, str(chosen.absolute())


def load_document(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("JSON input must be a string or a dictionary.")
    try:
        result = json.loads(value or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("Invalid JSON input: " + str(error)) from error
    if not isinstance(result, dict):
        raise ValueError("JSON input must contain an object at the top level.")
    return result


def _components(path):
    """A limited, safe JSON path: foo.bar, list[0].name, and quoted keys."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Enter a JSON path, e.g. controls.eye_detailer.enabled.")
    import re
    expr = path.strip()
    pieces = []
    index = 0
    while index < len(expr):
        if expr[index] == ".":
            index += 1
            continue
        if expr[index] == "[":
            end = expr.find("]", index)
            if end < 0:
                raise ValueError("Unclosed [ in JSON path.")
            key = expr[index + 1:end].strip()
            if key.startswith(("'", '"')):
                try:
                    key = json.loads(key) if key[0] == '"' else key[1:-1]
                except ValueError as error:
                    raise ValueError("Invalid quoted JSON path key.") from error
            elif key.isdecimal():
                key = int(key)
            else:
                raise ValueError("Use a numeric index or quoted key in [...].")
            pieces.append(key)
            index = end + 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", expr[index:])
        if match is None:
            raise ValueError("Invalid JSON path near: " + expr[index:])
        pieces.append(match.group())
        index += len(match.group())
        if index < len(expr) and expr[index] not in ".[":
            raise ValueError("Invalid JSON path separator.")
    return pieces


def get_field(document, path):
    current = load_document(document)
    for component in _components(path):
        if isinstance(component, int):
            if not isinstance(current, list) or not 0 <= component < len(current):
                return None, False
            current = current[component]
        elif isinstance(current, dict) and component in current:
            current = current[component]
        else:
            return None, False
    return current, True


def bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0", ""}:
            return False
    return default


def typed_field(document, path, default_string="", default_boolean=False,
                default_int=0, default_float=0.0):
    """Stable ComfyUI outputs: (str, bool, int, float, found)."""
    value, found = get_field(document, path)
    if not found or value is None:
        return (default_string, default_boolean, default_int, default_float, False)
    if isinstance(value, (list, dict)):
        string = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, bool):
        string = "true" if value else "false"
    else:
        string = str(value)
    boolean = bool_value(value, default_boolean)
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite value.")
        integer = int(number)
    except (ValueError, TypeError, OverflowError):
        number = float(default_float)
        integer = int(default_int)
    return (string, boolean, integer, number, True)


def has_tag(document, tag):
    parsed = load_document(document)
    tags = parsed.get("tags", [])
    return isinstance(tags, list) and isinstance(tag, str) and tag.strip() in tags


def conditional_prompt(default_prompt, override_prompt, condition):
    if bool_value(condition) and isinstance(override_prompt, str) and override_prompt.strip():
        return override_prompt, True
    return str(default_prompt), False


def sidecar_signature(image_path):
    """Return content-aware change signature so ComfyUI invalidates cached nodes."""
    path = sidecar_for_image(image_path)
    if not path.is_file():
        return ("missing", str(path.absolute()))
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(65536), b""):
            h.update(piece)
    return (str(path.absolute()), h.hexdigest())
