"""Tag-based prompt routing and dependency-lazy image bypass helpers.

No ComfyUI import in this module, allowing fast standalone tests.
"""
from __future__ import annotations

import csv
import json

from .sidecar import load_document, validate_document


def select_tag_prompt(sidecar_json, default_prompt, mapping_json,
                      priority_csv="", strict_single_match=False):
    """Return (prompt, matching tag, used default, count of matching tags).

    Mappings have exact, case-sensitive tag keys. Priority is deterministic:
    explicitly listed tags first in order, followed by other mapping keys
    in JSON insertion order. Duplicated tags in the source count only once.
    """
    document = validate_document(load_document(sidecar_json))
    tags = document.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("Sidecar tags must be a list of strings.")
    if not isinstance(default_prompt, str):
        raise ValueError("Default prompt must be a string.")

    if isinstance(mapping_json, dict):
        mapping = mapping_json
    elif isinstance(mapping_json, str):
        try:
            mapping = json.loads(mapping_json.strip() or "{}")
        except json.JSONDecodeError as error:
            raise ValueError("Invalid tag prompt mapping JSON: " + str(error)) from error
    else:
        raise ValueError("Tag prompt mapping must be a JSON object.")
    if not isinstance(mapping, dict):
        raise ValueError("Tag prompt mapping must be a JSON object: {tag: prompt}.")
    for tag, prompt in mapping.items():
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError("All mapped tags must be non-empty strings.")
        if not isinstance(prompt, str):
            raise ValueError("Prompt for tag '" + tag + "' must be a string.")

    if not isinstance(priority_csv, str):
        raise ValueError("Tag priority must be comma-separated text.")
    try:
        priority = [tag.strip() for tag in next(csv.reader([priority_csv]), []) if tag.strip()]
    except csv.Error as error:
        raise ValueError("Invalid tag priority list: " + str(error)) from error
    unknown = [tag for tag in priority if tag not in mapping]
    if unknown:
        raise ValueError("Tag priority refers to unmapped tag(s): " + ", ".join(unknown))

    order = list(dict.fromkeys(priority + list(mapping.keys())))
    matched = set(tags).intersection(mapping)
    matched_count = len(matched)
    if strict_single_match and matched_count > 1:
        raise ValueError(
            "More than one mapped tag matched: " +
            ", ".join(tag for tag in order if tag in matched)
        )
    for tag in order:
        if tag in matched:
            return mapping[tag], tag, False, matched_count
    return default_prompt, "", True, 0
