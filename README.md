# ComfyUI Image Utils

PNG provenance backup: `image_sidecar` iTXt (legacy `krea_sidecar` reads remain supported).

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

## Lifetime provenance and embedded backup (new)

A sidecar is a **persistent lifetime record**, not just a temporary prompt
override. The original generation metadata is captured by Image-Compare on the
first cull/export and stored under `origin`, including saved ComfyUI execution
graph, workflow, seed input values, and prompt inputs where available. Some
dynamic prompt nodes only save their inputs rather than the final expanded text;
the record makes this distinction clear rather than inventing a resolved prompt.

Two additional nodes make the record follow processed images:

**Image Utils · Append Processing Event** takes `sidecar_json` from Image
Sidecar Loader, the *actual prompt text* used in a detailer, a stage label
(e.g. `eye-detailer`), optional settings JSON, input filename and seed. It
appends an entry to `history` and passes the complete sidecar JSON onward
without replacing `origin`.

**Image Utils · Save Image + Sidecar (Embedded)** takes the processed IMAGE
and updated `sidecar_json` and saves both the new PNG and its JSON `.sidecar`.
It ALSO embeds a compressed PNG iTXt backup with key `image_sidecar`, and
preserves ComfyUI's usual `prompt` and `workflow` PNG metadata. It can
optionally archive the current execution graph and UI workflow in the
`image-save` history entry (enabled by default). Select it as your Save Image
node for this stage.

For example:

```text
Sequential Image Loader IMAGE ────────────────> detailer ──────> Save Image + Sidecar (Embedded)
                     file_path                   ▲                      ▲
                         │                       │                      │
                         ▼                       │                      │
                 Image Sidecar Loader            │                      │
                         │ json                  │                      │
                         ├────> Tag Checker ────> Prompt Selector       │
                         │                              │               │
                         │                         actual prompt        │
                         │                              │               │
                         └──────> Append Processing Event <─────────────┘
                                  stage=eye-detailer
                                  settings_json={"denoise":0.2}
```

(The selected prompt connects to your text encoder **and** Append Processing
Event. The output from Append Processing Event connects to the Save node's
`sidecar_json` input.)

If the external sidecar goes missing, **Image Sidecar Loader automatically
recovers the embedded `image_sidecar`** from the PNG. An external sidecar takes
precedence when present because it may contain later edits. Image-Compare also
uses the same precedence and has a **Provenance** viewer and explicit **Restore
Sidecar** action.

Sample lifetime record:

```json
{
  "version": 1,
  "tags": ["eyes-closed"],
  "controls": {},
  "prompts": {},
  "origin": {
    "source_filename": "original.png",
    "seeds": [{"value": "12345"}],
    "metadata": {"workflow": {"nodes": ["original-generation"]}}
  },
  "history": [
    {"stage": "select-sort", "timestamp": "2026-11-12T12:00:00+00:00"},
    {
      "stage": "eye-detailer",
      "timestamp": "2026-11-12T12:10:00+00:00",
      "actual_prompt": "Naturally closed eyelids, no iris",
      "settings": {"denoise": 0.2}
    },
    {"stage": "image-save", "output_filename": "detailer_00001_.png"}
  ]
}
```

**Save is currently PNG-only** for embedded backups. Images and external
sidecars are saved together; the PNG itself also contains the recovery copy.
Removing both the PNG metadata and the external sidecar is irreversible.
The existing nodes remain read-only; only Save Image + Sidecar writes new
output images. This node doesn't modify input images.

## Operational notes

- The reader looks for files on the **ComfyUI backend's filesystem**. If ComfyUI runs on a GPU pod, you must copy the images and matching sidecars to that pod.
- Spaces and Unicode characters in image names work normally. Filenames are handled as file paths, not shell commands.
- The reader's IS_CHANGED hook checks file content, so edited sidecars invalidate the cached node output.
- These four nodes are **read-only**; neither images nor sidecars are modified.
- A configurable **Add Output** node with dynamically typed sockets can be developed later. It requires synchronized Python/backend and JavaScript/frontend socket definitions to behave reliably with differing images.
