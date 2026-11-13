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

## Core sidecar nodes

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

## Lazy detailer bypass, per-tag prompt selection, and inline previews

Four more nodes are available under **Image Utils / Sidecars**:

| Node | Key inputs | Outputs |
| --- | --- | --- |
| **Lazy Image Bypass** | bypass BOOLEAN, passthrough_image IMAGE, processed_image IMAGE | image IMAGE, bypassed BOOLEAN |
| **Tag Prompt Selector** | sidecar_json STRING, default_prompt STRING, mapping_json STRING, priority_csv STRING, strict_single_match BOOLEAN | selected_prompt STRING, matched_tag STRING, used_default BOOLEAN, matched_count INT |
| **Inline Image Preview** | image IMAGE, enabled BOOLEAN, max_preview_edge INT, batch_frames INT | image IMAGE (unchanged) + ComfyUI UI thumbnail |
| **Inline Crop Preview** | image IMAGE, optional crop_image IMAGE and/or crop_mask MASK, same preview controls | image IMAGE (unchanged) + UI thumbnail(s) |

### Skip face detailer entirely for no-face

Connect the incoming full image to **passthrough_image** and the output of your
face detailer group to **processed_image**. Feed **JSON Tag Checker** with tag
`no-face` into the bypass's **bypass** BOOLEAN input.

```text
Sequential Image Loader
  image ────────────────────────────────> [Get/Set: FACE_IN] ────────┐
  file_path → Image Sidecar Loader                                  │
                  │ json                                            │
                  └── JSON Tag Checker (tag: no-face)               │
                             │ has_tag                              │
                             ▼                                      ▼
                      Lazy Image Bypass  ← passthrough_image ── Get: FACE_IN
                       bypass = has_tag
                       processed_image ← Get: FACE_DETAILED
                             │ image
                             ▼
                        next stage

Inside FACE DETAILER GROUP:
    Get: FACE_IN → Face Detailer → Inline Crop Preview → Set: FACE_DETAILED
                                          ▲
                                          └── optional crop_image / crop_mask
```


- With **no-face present**, the bypass requests only `passthrough_image`.
  The detailer and its inline preview aren't evaluated.
- Otherwise the bypass requests `processed_image`, which executes the
  detailer (and inline preview) before continuing.
- The regular **rgthree group bypass control** can remain as a separate
  *manual* override for debugging; per-image routing is handled by this node.

ComfyUI's **lazy input** mechanism requests only the selected input branch.
**Important:** Other independent output nodes can still force a detailer
to execute. Standard **Preview Image**, Save Image or a standalone preview-crop
output connected to an internal detailer result will defeat lazy skipping.
Remove/mute those independent outputs, and replace them with an inline preview
node placed **in the path to processed_image**. The inline preview must have
its IMAGE output connected onward: unconnected inline previews do not run.

KJNodes Get/Set and similar virtual wiring can be used **as long as the
connections become normal graph dependencies when the prompt is submitted**.
Physical wires are not required. You can confirm behavior by queueing a
`no-face` image and checking that the face sampler isn't executed.
This has been exercised in unit tests without a live GPU ComfyUI canvas.

### Select one eye detailer prompt from image tags

Send the **json** output of Image Sidecar Loader to **Tag Prompt Selector**.
Set **mapping_json** to, for example:

```json
{
  "eyes-closed": "Naturally closed eyelids, detailed eyelashes, delicate lash roots, no visible iris",
  "eyes-half-closed": "Half-closed eyelids, subtle iris visible beneath lashes, natural skin texture",
  "bright-green-eyes": "Bright green irises, accurate pupils, detailed sclera, natural eyelashes"
}
```


Set **priority_csv** to `eyes-closed, eyes-half-closed, bright-green-eyes`.

The selector chooses the *first matching tag in priority order*. Unlisted keys
in mapping_json follow the order in the JSON object. When none match, it emits
**default_prompt**. If more than one mapping matches, **matched_count** reports
the ambiguity and the first priority match wins. Enable
**strict_single_match** to fail instead. Tags are exact and case-sensitive;
`no-eyes` can independently control a bypass while the selected prompt
controls the eye detailer when present.

```text
Image Sidecar Loader.json ───> Tag Prompt Selector
                                   │ selected_prompt (STRING)
                                   ├──────────> CLIP Text Encode ──> eye detailer
                                   └──────────> Append Processing Event.actual_prompt
```


You can keep the prompt default as editable node text, or convert the
default_prompt widget to an input and connect a Get node for an existing
prompt. The selector produces **prompt text**, not CONDITIONING directly.

### Inline previews for image, crop and mask debugging

**Inline Image Preview** shows whichever image flows through it and returns
*the same IMAGE tensor* unchanged. **Inline Crop Preview** passes through
the full processed IMAGE while showing the optional crop image and/or mask
used internally by the detailer. Both return ComfyUI UI image previews, **but
neither is marked OUTPUT_NODE**, so they are only evaluated when their
passthrough IMAGE is needed downstream. They do not themselves require their
upstream branch when the lazy bypass selects something else.

Use **max_preview_edge** (default 1024) and **batch_frames** (default 1)
to bound temporary preview size. Diagnostic files go into ComfyUI's temp
directory; the forwarded IMAGE is never resized or re-encoded. Set
**enabled=false** to avoid temporary preview writes. Unlike a standard
Preview Image, merely placing one of these inline nodes in a group does not
create an independently requested output endpoint.

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
- The loader, extractors, routing, and inline previews do not modify input images or sidecars.
- A configurable **Add Output** node with dynamically typed sockets can be developed later. It requires synchronized Python/backend and JavaScript/frontend socket definitions to behave reliably with differing images.
