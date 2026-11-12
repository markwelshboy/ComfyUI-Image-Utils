# ComfyUI Image Utils

Generic sidecar-driven ComfyUI utility nodes. Works directly with the full **file_path** STRING output of the [shootthesound Sequential Image Loader](https://github.com/shootthesound/ComfyUI-SequentialImageLoader); no change to that node is required.

## Install

    cd /opt/ComfyUI/custom_nodes
    git clone https://github.com/markwelshboy/ComfyUI-Image-Utils.git

Restart ComfyUI. For updates, run git pull origin main inside the repository, then restart.

The nodes appear under **Image Utils / Sidecars**. No extra dependencies are required beyond standard Python and ComfyUI.

## Sidecar filename and schema

    /workspace/input/img1.png
    /workspace/input/img1.sidecar

    /workspace/input/image with spaces.png
    /workspace/input/image with spaces.sidecar

Each .sidecar is a UTF-8 JSON file. A useful example:

    {
      "version": 1,
      "tags": ["eyes-closed", "face-detailer"],
      "controls": {
        "eye_detailer": {"enabled": false, "denoise": 0.2},
        "face_detailer": {"enabled": true, "denoise": 0.35}
      },
      "prompts": {
        "eye_detailer": "Closed eyelids, natural eyelashes, no visible iris"
      }
    }

The schema is extensible. You may add other nested keys without changing the sidecar loader. **Tags** describe visible conditions; **controls** and **prompts** specify desired pipeline actions.

If two images share a stem (for example img.png and img.jpg in one folder), Image-Compare writes img.png.sidecar and img.jpg.sidecar to avoid overwriting one. The loader looks for the full-filename variant first, then the conventional stem.sidecar name.

If no sidecar exists, the loader returns exists=false and a valid empty document (version 1, empty tags/controls/prompts). Malformed JSON raises an error identifying the file; it is never silently ignored.

## Four initial nodes

| Node | Inputs | Outputs |
| --- | --- | --- |
| **Image Sidecar Loader** | image_path STRING | json STRING, exists BOOLEAN, sidecar_path STRING |
| **JSON Field Extractor** | json STRING, field_path STRING, typed defaults | text STRING, boolean BOOLEAN, integer INT, number FLOAT, found BOOLEAN |
| **JSON Tag Checker** | json STRING, tag STRING | has_tag BOOLEAN |
| **Conditional Prompt** | default_prompt STRING, override_prompt STRING, condition BOOLEAN | prompt STRING, using_override BOOLEAN |

### Eye-detailer routing

    Sequential Image Loader
      ├── image ─────────────────────────────────────────> eye detailer
      └── file_path → Image Sidecar Loader → json → JSON Tag Checker
                                                       tag: eyes-closed
                                                       │ has_tag
                                                       ▼
                                                 Conditional Prompt
                                   default_prompt: "detailed iris..."
                                   override_prompt: "Closed lids, no iris..."
                                                       │ prompt STRING
                                                       ▼
                                                  CLIP Text Encode
                                                       │ CONDITIONING
                                                       ▼
                                                   eye detailer

A separate eyes-half-closed tag can select an intermediate prompt using a second Conditional Prompt. The final prompt is always a STRING; there is no dependence on Any Switch's None or empty-string handling.

### JSON field paths

Use JSON Field Extractor for arbitrary structured controls:

- controls.eye_detailer.enabled → BOOLEAN
- controls.face_detailer.denoise → FLOAT
- prompts.eye_detailer → STRING
- tags[0] → first tag
- controls["eye detailer"].enabled → keys containing spaces

All outputs have stable types, regardless of what each image's JSON contains. Missing values yield the user-configured typed defaults plus found=false. A JSON boolean false is correctly interpreted as False (not as a truthy string).

The outputs can be connected to existing compatible rgthree, KJNodes, and detailer controls. ComfyUI's usual widget-to-input conversion may be necessary for some external nodes.

## Operational notes

- The reader looks for files on the **ComfyUI backend's filesystem**. If ComfyUI runs on a GPU pod, you must copy the images and matching sidecars to that pod.
- Spaces and Unicode characters in image names work normally. Filenames are handled as file paths, not shell commands.
- The reader's IS_CHANGED hook checks file content, so edited sidecars invalidate the cached node output.
- These four nodes are **read-only**; neither images nor sidecars are modified.
- A configurable **Add Output** node with dynamically typed sockets can be developed later. It requires synchronized Python/backend and JavaScript/frontend socket definitions to behave reliably with differing images.
