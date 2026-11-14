"""Canonical generation provenance and safe, predictable image-save naming.

No ComfyUI imports: both the generation and detailer pipelines use these
functions, which are tested without GPU or a running frontend.
"""
from __future__ import annotations

import copy
from datetime import datetime
import json
import os
from pathlib import Path, PureWindowsPath
import re

VALID_TRACKING = re.compile(r"[0-9]{1,16}\Z")
TRAILING_COUNTER = re.compile(r"(?:^|[_\-\s])([0-9]+)\Z")
TOKENS = {"input_name", "tracked_count", "counter", "seed", "date", "time", "batch", "stage"}
TOKEN_PATTERN = re.compile(r"%([^%]+)%")
MAX_ATTEMPTS = 100000


def new_generation_document(positive_prompt, negative_prompt="", seed=-1,
                            model_name="", settings_json="{}"):
    """Create a sidecar with explicit runtime text, not graph-derived guesses."""
    if not isinstance(positive_prompt, str):
        raise ValueError("positive_prompt must be a STRING.")
    if not isinstance(negative_prompt, str):
        raise ValueError("negative_prompt must be a STRING.")
    if not isinstance(model_name, str):
        raise ValueError("model_name must be a STRING.")
    if type(seed) is not int or seed < -1 or seed > 0xffffffffffffffff:
        raise ValueError("seed must be a nonnegative integer or -1 when unknown.")
    try:
        settings = json.loads(settings_json or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("settings_json must be valid JSON.") from exc
    if not isinstance(settings, dict):
        raise ValueError("Generation settings must be a JSON object.")
    record = {
        "version": 1,
        "tags": [], "controls": {},
        "prompts": {"generation": {
            "positive": positive_prompt,
            "negative": negative_prompt,
        }},
        "origin": {"generation": {
            "settings": settings,
        }},
        "history": [],
    }
    if seed >= 0:
        record["origin"]["generation"]["seed"] = seed
    if model_name.strip():
        record["origin"]["generation"]["model"] = model_name.strip()
    return record


def _safe_stem(source_name):
    source = str(source_name or "").strip().replace("\\", "/").rstrip("/")
    stem = source.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    # Preserve spaces and Unicode letters, but never allow directory traversal.
    result = "".join(ch if (ch.isalnum() or ch in " _-.()") else "_" for ch in stem)
    return result.strip(" .") or "image"


def _safe_component(name):
    if not isinstance(name, str) or not name or len(name) > 240:
        raise ValueError("Generated filename must contain 1–240 characters.")
    if name in {".", ".."} or name.endswith((" ", ".")):
        raise ValueError("Generated filename must not end with a dot or space.")
    if any(ch in name for ch in "/\\\x00<>:\"|?*") or any(ord(ch) < 32 for ch in name):
        raise ValueError("Filename template cannot produce paths or unsafe characters.")
    if re.fullmatch(r"(?i)(con|aux|nul|prn|com[1-9]|lpt[1-9])", name):
        raise ValueError("Generated filename is a reserved device name.")
    return name


def source_counter(source_name):
    name = _safe_stem(source_name)
    match = TRAILING_COUNTER.search(name)
    return match.group(1) if match else None


def read_tracking(doc, source_name="", explicit=""):
    """Sidecar ID > filename; explicit input wins. Never silently renumber."""
    origin = doc.get("origin", {}) if isinstance(doc, dict) else {}
    stored = origin.get("tracking_id") if isinstance(origin, dict) else None
    if explicit is not None and str(explicit).strip():
        result = str(explicit).strip()
        if stored is not None and str(stored) != result:
            raise ValueError("An existing origin.tracking_id is immutable; "
                             "the explicit tracking_id conflicts with the saved image.")
    else:
        result = stored if stored is not None else source_counter(source_name)
    if result is not None and not VALID_TRACKING.fullmatch(str(result)):
        raise ValueError("Tracking ID must be 1–16 digits.")
    return str(result) if result is not None else None


def _inside(path, root):
    return path == root or root in path.parents


def output_folder(output_root, output_directory="", allowed_roots=None):
    """Resolve paths under Comfy's output root or explicitly trusted roots.

    IMAGE_UTILS_ALLOWED_OUTPUT_DIRS may list additional absolute trusted
    destinations separated by os.pathsep. Symlink escapes are rejected.
    """
    main = Path(output_root).expanduser().resolve()
    extra = (os.environ.get("IMAGE_UTILS_ALLOWED_OUTPUT_DIRS") or "").split(os.pathsep)
    roots = [main] + [Path(p).expanduser().resolve() for p in extra if p]
    if allowed_roots:
        roots.extend(Path(p).expanduser().resolve() for p in allowed_roots)
    raw = str(output_directory or "").strip()
    if "\x00" in raw:
        raise ValueError("Output directory contains an invalid character.")
    if not raw:
        folder = main
    else:
        candidate = Path(raw).expanduser()
        folder = (candidate if candidate.is_absolute() else main / candidate).resolve()
    if not any(_inside(folder, root) for root in roots):
        raise ValueError("Save directory is outside ComfyUI's output directory. "
                         "Set IMAGE_UTILS_ALLOWED_OUTPUT_DIRS explicitly to permit another root.")
    return folder


def expand_filename(template, *, source_name="", tracked_count="", counter=0,
                    seed=-1, batch=0, stage="", padding=4, now=None):
    if not isinstance(template, str) or not template.strip():
        raise ValueError("Enter a filename template.")
    if type(padding) is not int or not 1 <= padding <= 12:
        raise ValueError("Counter padding must be between 1 and 12.")
    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        raise ValueError("Counter must be nonnegative.")
    if type(batch) is not int or batch < 0:
        raise ValueError("Batch index must be nonnegative.")
    if type(seed) is not int or seed < -1:
        raise ValueError("Seed must be an integer.")
    now = now or datetime.now()
    clean = template.strip()
    if clean.lower().endswith(".png"):
        clean = clean[:-4]
    found = TOKEN_PATTERN.findall(clean)
    invalid = set(found) - TOKENS
    if invalid:
        raise ValueError("Unknown filename token(s): " + ", ".join(sorted(invalid)))
    values = {
        "input_name": _safe_stem(source_name),
        "tracked_count": str(tracked_count).zfill(padding),
        "counter": str(counter).zfill(padding),
        "seed": str(seed) if seed >= 0 else "unknown",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H%M%S"),
        "batch": str(batch).zfill(3),
        "stage": _safe_stem(stage or "processed"),
    }
    value = TOKEN_PATTERN.sub(lambda match: values[match.group(1)], clean)
    if "%" in value:
        raise ValueError("Invalid or unclosed filename template token.")
    value = _safe_component(value)
    if len((value + ".png").encode("utf-8")) > 240:
        raise ValueError("Generated filename exceeds the filesystem's byte limit.")
    return value + ".png"


def companions_exist(folder, filename, reserved=None):
    """Respect BOTH image and sidecar and protection-mask collisions."""
    p = Path(folder) / filename
    base = p.with_suffix("")
    options = (p, p.with_suffix(".sidecar"), p.with_suffix(".protection_mask"),
               Path(str(p) + ".sidecar"))
    return any(x.exists() or x in (reserved or set()) for x in options)


def allocate_save_name(folder, template, *, source_name="", tracked_count=None,
                       seed=-1, stage="", batch=0, batch_size=1,
                       padding=4, start_counter=0, collision_policy="append_revision",
                       reserved=None, now=None):
    """Return (filename, resolved_tracking_id, sequential_counter, revision).

    Tracked IDs are fixed for named originals. New images with no ID can
    allocate one using a sequence, independently of the output counter.
    """
    if collision_policy not in ("error", "append_revision", "increment_counter"):
        raise ValueError("Unknown collision policy.")
    if type(start_counter) is not int or not 0 <= start_counter <= 999999999:
        raise ValueError("Starting counter must be 0–999,999,999.")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be positive.")
    if tracked_count is not None and not VALID_TRACKING.fullmatch(str(tracked_count)):
        raise ValueError("Tracked counter must contain digits.")
    if batch_size > 1 and "%batch%" not in template:
        # Guarantee unique images in one batch, even for identical source names.
        suffix = "_b" + str(batch).zfill(3)
    else:
        suffix = ""
    has_output_count = "%counter%" in template
    fixed_tracking = tracked_count is not None
    # If neither source nor origin provides a tracked ID, assign consecutive
    # IDs without changing an original file's existing ID.
    for offset in range(MAX_ATTEMPTS):
        counter = start_counter + offset
        proposed_id = str(tracked_count) if fixed_tracking else str(counter).zfill(padding)
        raw = expand_filename(template, source_name=source_name,
                              tracked_count=proposed_id, counter=counter, seed=seed,
                              batch=batch, stage=stage, padding=padding, now=now)
        stem = Path(raw).stem + suffix
        candidate = stem + ".png"
        if not companions_exist(folder, candidate, reserved):
            return candidate, proposed_id, counter, 1
        if collision_policy == "error":
            raise FileExistsError("Image, sidecar or protection mask already exists: " + str(Path(folder) / candidate))
        if collision_policy == "append_revision":
            if not fixed_tracking and ("%tracked_count%" in template or "%counter%" in template):
                # Newly generated images without a source ID should allocate
                # consecutive IDs, not multiple revisions of ID 0000.
                continue
            for revision in range(2, MAX_ATTEMPTS):
                candidate = f"{stem}_v{revision:02d}.png"
                if not companions_exist(folder, candidate, reserved):
                    return candidate, proposed_id, counter, revision
            raise FileExistsError("No free revision suffix for " + stem)
        # For a fixed ID and a template without %counter%, trying higher
        # output counters cannot produce another filename.
        if not has_output_count and fixed_tracking:
            raise ValueError("increment_counter requires %counter% for a tracked input name.")
    raise FileExistsError("Could not allocate an unused output filename.")
