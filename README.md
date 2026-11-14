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

## AnyPaint masks from Image-Compare polygons

**MR Sidecar Polygon Mask Extractor** appears under **Image Utils / Sidecars**.

Connect:
- `image` to the full-resolution IMAGE from the Sequential Image Loader.
- `sidecar_json` to the JSON STRING from **Image Sidecar Loader**.
- `mask_name` to `anypaint` (default).

It returns exactly three typed outputs:
- `mask` **MASK** — standard float32 [batch, height, width], black = don't edit,
  white = editable region. Additive polygons and subtractive holes are composed
  in saved order.
- `mask_present` **BOOLEAN** — true only if enabled and at least one additive
  region survives rasterization; false for absent, disabled or empty masks.
- `prompt` **STRING** — associated AnyPaint inpaint prompt, or empty string
  when no valid active mask exists.

Sidecars contain editable, normalized polygon coordinates and reference
dimensions, not raster masks:

```json
{
  "masks": {
    "anypaint": {
      "enabled": true,
      "reference_size": [1024, 1536],
      "prompt": "Remove misplaced tattoo and restore natural skin texture",
      "regions": [
        {"operation": "add", "points": [[0.22,0.34],[0.33,0.32],[0.35,0.42],[0.21,0.44]]}
      ]
    }
  }
}
```

The extractor renders the mask at the incoming IMAGE resolution. Matching
aspect ratio is required (within 1%); crops/reframing are deliberately rejected
because stale polygons could cover the wrong region. Scaling the same composition
is allowed. Image batches receive identical masks when the image geometry is
shared. Missing masks produce an all-black MASK and `mask_present=false`.

**Lazy AnyPaint:** Route `mask_present` to a KJ lazy switch choosing the
unprocessed input IMAGE when false and AnyPaint output when true. Ensure
AnyPaint's own output and preview nodes do not have independent connections
that force the expensive branch. The prompt goes into your inpaint text encoder.
These polygons are independent of the LoneCat accumulated `lc_protect` mask
and do not modify that protection data.

## Initial generation: canonical resolved prompt and seed

**MR Sidecar Initialize (Generation)** is available under **Image Utils /
Sidecars**. Connect the actual final resolved prompt STRING (the same one fed
into your Krea2/WAN/CLIP/text encoder). Optionally connect the actual seed,
negative prompt, model name and a `settings_json` object. It produces an
ordinary `sidecar_json` STRING for **Image Utils · Save Image + Sidecar
(Embedded)**, without requiring an incoming sidecar.

```text
PromptLibrary resolved STRING ──┬──→ Text Encoder ──→ Generation → IMAGE ┐
                                └──→ MR Sidecar Initialize              │
                                           ▲ seed, model, settings       │
                                           └──→ sidecar_json ────────────┤
                                                      Save + Sidecar ←───┘
```

The canonical fields are:

```json
{
  "version": 1, "tags": [], "controls": {},
  "prompts": {"generation": {
    "positive": "The actual resolved generation prompt",
    "negative": "Optional negative text"
  }},
  "origin": {"generation": {
    "model": "Krea 2", "seed": 123, "settings": {"steps": 10}
  }},
  "history": []
}
```

The prompt comes from the actual resolved node output, **not inferred from
the saved ComfyUI workflow graph**. The full current workflow stays in the
normal ComfyUI PNG metadata, while the compact original prompt and seed live
in `image_sidecar` (embedded PNG) and the companion JSON `.sidecar`.

For simple pipelines you can **omit sidecar_json entirely** from the Save
node and connect its optional `positive_prompt` / `seed` inputs directly.
It constructs the same canonical JSON. If no JSON or prompt is supplied, it
creates an empty but valid lifetime sidecar, without pretending to know the
resolved prompt. If an existing JSON is supplied, its original generation
prompt and provenance are preserved rather than overwritten by detailer text.

### Intelligent filenames for generation and detailer output

The existing **Image Utils · Save Image + Sidecar (Embedded)** node has
optional controls; the old `filename_prefix` + ComfyUI counter behavior is
unchanged if **filename_template** and **output_directory** are left blank.
Both old and new workflows keep the same node ID, PNG workflow metadata, and
PNG + .sidecar + optional .protection_mask output.

For your detailer flow, connect the full source `file_path` from Sequential
Image Loader to **source_name**, and set:

```text
output_directory: /workspace/ComfyUI/output_gpu0/Final
stage: after_detailer_pipe_and_upscaled
filename_template: %input_name%_%stage%_%tracked_count%
counter_padding: 4
collision_policy: append_revision
```

For source `culled_for_detailing_0087.png` the result is:

```text
culled_for_detailing_0087_after_detailer_pipe_and_upscaled_0087.png
culled_for_detailing_0087_after_detailer_pipe_and_upscaled_0087.sidecar
culled_for_detailing_0087_after_detailer_pipe_and_upscaled_0087.protection_mask  (optional)
```

| Token | Meaning |
| --- | --- |
| `%prefix%` | The `filename_prefix` widget value (basename), included explicitly in custom templates |
| `%input_name%` | Source filename stem, without directory or extension |
| `%tracked_count%` | Immutable `origin.tracking_id`, otherwise numeric source suffix, otherwise allocated ID starting 0000 |
| `%aligned_counter%` | Counter parsed from current source filename suffix, falling back to tracked ID; useful when curated numbering differs from original generation order |
| `%counter%` | Independent collision-aware sequential output counter, starting at `counter_start` |
| `%stage%` | Current saver processing-stage name |
| `%seed%` | Connected seed, or original `origin.generation.seed`; `unknown` when unavailable |
| `%date%` / `%time%` | Server-local current date / time |
| `%batch%` | Three-digit current batch index |

**Curated renumbering:** If the image was originally `generated_0001.png`
but Image-Compare exported it as `curated_set_0087.png`, the original
`origin.tracking_id` might still be `0001`. To produce
`curated_set_0087_after_detailer_pipe_and_upscaled_0087.png` while
**preserving original lineage**, use `%aligned_counter%` instead of
`%tracked_count%`. These two tokens are intentionally different.

**Important: custom templates replace legacy prefix behavior.** If
`filename_template` is set, the saver uses it as the *entire filename*, and
does not automatically prepend `filename_prefix`. To include that field,
use `%prefix%` in your template. For example:

```text
filename_prefix: image_gen_2k
filename_template: %prefix%_%counter%
output_directory: trial2k
→ trial2k/image_gen_2k_0000.png
→ trial2k/image_gen_2k_0001.png
```

The preview now offers a **+ Filename prefix** button and explains when
the field is unused. Templates that deliberately use
`%input_name%_%stage%_%tracked_count%` are unchanged, and clearing the
template still uses ComfyUI's original `filename_prefix` behavior.

The optional explicit `tracking_id` input accepts 1–16 digits. If an
existing sidecar already has `origin.tracking_id`, a conflicting ID raises
an error rather than silently rewriting the original identity. Legacy
source filenames without a trailing numeric suffix receive increasing
IDs (0000, 0001, ...). Counter padding is preserved when the incoming
source has leading zeros. Batch outputs without `%batch%` automatically
receive distinct `_b000`, `_b001` suffixes.

The **collision policy** defaults to `append_revision`: a repeated save
of a tracked image becomes `..._v02.png`, while its tracking ID remains
unchanged. `error` refuses collisions; `increment_counter` advances
`%counter%` for filenames containing that token. Existing image,
sidecar, and mask companions are never knowingly overwritten. Each save
adds a compact `image-save` event including input filename, output
filename and directory, tracking ID, revision and stage. The full workflow
is included in history only when `include_current_workflow_in_history`
is enabled; **disable this for compact long-lived sidecars**, because
ComfyUI's standard PNG workflow metadata is still saved separately.

**Directory safety:** Relative `output_directory` values are resolved
below the configured ComfyUI output directory. Absolute paths work if
they are inside that root. To allow another location explicitly, set
`IMAGE_UTILS_ALLOWED_OUTPUT_DIRS` to a platform-separated list of trusted
absolute roots before starting ComfyUI. Symlink escapes outside permitted
roots are rejected. Files written to additional roots are saved, but their
image thumbnails may not appear in ComfyUI's normal output viewer.

A small on-node **filename-token picker and live estimate** appears in
the frontend. When dynamic inputs are connected, the estimate is only
illustrative: **Last save** displays the actual resolved path returned by
the backend after execution. As with other ComfyUI DOM widgets, a frontend
restart/refresh may be needed after upgrading the extension.

### Compact Save Image interface and saved-image preview

The existing **Image Utils · Save Image + Sidecar (Embedded)** node now uses a
custom compact frontend, without adding or renaming Python inputs or changing
the underlying output/sidecar behavior.

**Collapsed by default:** a short toolbar (▸ Settings, ⚙ preferences, PNG +
sidecar indicator), a **persistent image preview**, and a saved-path/status
line. The saved image appears in the preview after generation, with
previous/next controls for multiple batch outputs. Click the image to open it
larger.

**Expanded settings:** compact, scrollable controls grouped into **Naming**,
**Output**, **Counters**, **Provenance**, and **Advanced Metadata**. Filename
token buttons and the reactive “Will save as” estimate live in the Naming
section. Existing sockets (IMAGE, sidecar_json, connected prompt, etc.)
remain available. Connected widget inputs are read-only in the custom panel,
since their actual values are supplied by upstream nodes.

The ⚙ preferences dialog adjusts image-preview height (180–700 px), whether
settings start collapsed, and compact spacing. These appearance preferences
persist **in the local browser**; actual filename, directory, counters,
and metadata remain saved with the ComfyUI workflow.

The backend now returns a separate \`mr_saved_previews\` UI array with each
saved filename, subfolder, display path, and browser preview availability.
Images inside the configured ComfyUI output tree are served via its normal
\`/view\` endpoint. If an explicitly allowed custom output directory lies
outside that served tree, saving still works and the panel shows the absolute
saved path, but explains that browser preview isn't available there. No
arbitrary filesystem paths are exposed as web URLs.

**Compatibility:** All original native widgets are **visually hidden**, not
removed or reordered. They remain the authoritative serializable values
and Python inputs. The single DOM preview/control helper remains explicitly
non-serializable. Named-value snapshots and shifted-widget validation are
unchanged. If the custom frontend fails to initialize, the node restores its
native controls rather than becoming unusable.

### Text-area labels and safe workflow widget migration

The saver has two multiline fields that ComfyUI ordinarily renders without
a heading. They are now visibly labeled **NEGATIVE PROMPT · optional**
(the upper large text box, before `model_name`) and
**GENERATION SETTINGS · JSON** (the lower box, after `model_name`).
The original widget names and order do **not** change, so existing graph
connections remain intact. You can leave the negative prompt blank and
the settings field at `{}`. Both fields matter only when the saver
initializes a new generation sidecar; an incoming `sidecar_json` takes
precedence.

Older ComfyUI versions can restore a workflow's `widgets_values`
positionally instead of by input name. If a saver gained new fields
between saves, its values might be shifted, e.g. `output_directory`
accidentally showing `generation`, an empty `stage`,
`counter_padding=0`, `counter_start=NaN`, or
`collision_policy=-1`.

For future saves, the saver now records a **name-keyed widget snapshot**
in its existing node `properties`. On load it uses this named mapping
(or ComfyUI's native `widgets_values_named` when available) to restore
values regardless of widget position. The non-serializable filename
preview is also explicitly excluded from positional saved widget lists.
No extra input widgets are added.

**Important limitation:** An already corrupted positional workflow
may contain plausible-looking but incorrect values, especially
`output_directory`, `stage` or `tracking_id`. The saver **will not
guess** what your original settings were. If it detects invalid
settings, an amber warning appears in the filename preview panel.
Select **Reset misaligned advanced settings** to deliberately reset
optional fields, keeping `filename_prefix`, `filename_template` and
existing connections. Review your desired output directory, stage,
tracking ID and counters before queueing, then save the workflow.
The backend refuses invalid settings before writing any files.

For an older workflow without obviously invalid values, the preview
also reminds you to check the settings once; re-saving it records the
named snapshot for future imports. A fresh node should load normally.

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
and optional updated `sidecar_json` and saves both the new PNG and its JSON `.sidecar`.
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

## Persistent protection masks: save and resume later

The existing **Image Utils · Save Image + Sidecar (Embedded)** node now has
an **optional `protection_mask: MASK` input**. Connect the accumulated
`protect_mask` output from **LC Pipe Out** (not an individual detailer's
per-stage MASK) to save the protection regions built up by all previous
LoneCat / MR pipe detailers.

For a saved image named `detailer_00001_.png`, the three companion records are:

```text
detailer_00001_.png             ← rendered image + embedded sidecar JSON
detailer_00001_.sidecar         ← editable JSON provenance, prompts, controls
detailer_00001_.protection_mask ← accumulated mask (lossless binary)
```

The `.protection_mask` file is a **compressed NPZ archive with a custom
extension**, containing a single **float32 (H,W) mask** and format version,
not a PNG or plain-text JSON. This preserves mask strengths and soft
feathered edges without the quantization of an 8-bit image. A batch of
images saves **one matching mask per output image**. Batch size and spatial
dimensions must match the saved images; mismatches fail instead of
silently broadcasting a mask onto the wrong image. Without an attached
mask, the Save node's original PNG + JSON behavior is unchanged.

### Save the accumulated mask

```text
Final MR Lazy Detailer ── LC_PIPE ─────► LC Pipe Out
                                           │           │
                                      IMAGE│           │protect_mask
                                           │           │
                                           ▼           ▼
                                    Save Image + Sidecar (Embedded)
                                           ▲
                                           │sidecar_json (as before)
```

Saving an explicit protection mask also records its companion filename in
the saved JSON's `image-save` history entry. **The mask itself is stored
only in the binary companion file**: PNG embedded metadata backs up the
JSON sidecar, not the protection mask. Transfer all three files if moving
to another machine or GPU pod.

### Read the mask and place it back in an LC pipe

Add **MR Load Protection Into Pipe** under
**Image Utils / MR Lazy Detailers**. Connect the current loaded image
and its **full filename STRING** from Sequential Image Loader:

```text
Sequential Image Loader ── file_path ────────────────────┐
                         IMAGE ────────────────────┐     │
                                                  ▼     ▼
Existing LC Pipe (in/edit) ── LC_PIPE (optional) ─► MR Load Protection Into Pipe
                                                           │
                                                           ├─ LC_PIPE → next MR Lazy Detailer
                                                           ├─ MASK    → optional mask preview
                                                           └─ found   → BOOLEAN
```

The loader reads `<stem>.protection_mask` (or the unambiguous
`<image filename>.protection_mask` variant). It attaches the saved mask
under `lc_protect` and calculates a **new LoneCat image fingerprint for
the current loaded IMAGE**. This is necessary because a saved 8-bit PNG
may have slightly different pixel values from the in-memory IMAGE that
was originally detailed. The stored mask is not altered.

You can pass an **optional existing LC_PIPE** to preserve your model, VAE,
conditioning, seed and sampler settings. Without it, the node creates a
minimal pipe holding just the image and protection; downstream detailers
still need their required sampling/model settings from an earlier LC Pipe.
When replacing a pipe's image, the node clears old cached `lc_found`
SAM3 detections. Existing protection in the input pipe is **replaced by
the saved mask**, rather than accidentally mixing protection from
different processing sessions.

The loader's **missing_policy** defaults to `error` to avoid silently
losing protections. Select `empty` only if a mixed folder intentionally
contains some images without mask companions: then `found=false` and the
pipe carries no protection for those images. Read and restore are
single-image operations because each companion belongs to one saved
image; feed one image at a time when iterating a folder.

Mask restore requires the same image geometry and spatial alignment.
Resizing, cropping, or moving features after saving would need a
corresponding mask transform; this loader intentionally refuses
dimension mismatches instead of retagging a misaligned mask.

## Operational notes

- The reader looks for files on the **ComfyUI backend's filesystem**. If ComfyUI runs on a GPU pod, you must copy the images and matching sidecars to that pod.
- Spaces and Unicode characters in image names work normally. Filenames are handled as file paths, not shell commands.
- The reader's IS_CHANGED hook checks file content, so edited sidecars invalidate the cached node output.
- The loader, extractors, routing, and inline previews do not modify input images or sidecars.
- A configurable **Add Output** node with dynamically typed sockets can be developed later. It requires synchronized Python/backend and JavaScript/frontend socket definitions to behave reliably with differing images.


## MR lazy LoneCat pipe detailers (experimental)

This is an **additive** integration with
[lonecatone23/ComfyUI_LC_MaskMaker_nodes](https://github.com/lonecatone23/ComfyUI_LC_MaskMaker_nodes).
It does **not** edit, unregister, monkeypatch, or replace the original LoneCat
detailers. Existing workflows using the original node IDs remain unchanged.

Five additional nodes are available under **Image Utils / MR Lazy Detailers**:

| Node | Purpose |
| --- | --- |
| **MR Lazy Smart Detailer (pipe)** | Runs the installed LC Smart Detailer (pipe) without being an independent OUTPUT_NODE |
| **MR Lazy Character Detailer (pipe)** | Equivalent adapter for LC Character Detailer (pipe) |
| **MR VRAM Cache Clear (Inline)** | Passes any value through unchanged; clears caches **only if requested by downstream** |
| **MR Conditional Preview Sink** | Conditional multi-input IMAGE/MASK previews plus on-node SKIPPED/SELECTED lamp |
| **MR Pipe Image Replace (Preserve Protection)** | Replaces LC_PIPE's image after an external processing stage while retaining accumulated LC protection |

### Preserve accumulated protection across a SEGS detailer

Use **MR Pipe Image Replace (Preserve Protection)** when an external
image-only processing stage changes pixels without changing the image's
shape or alignment. The node takes exactly **two required inputs**:
`pipe: LC_PIPE` and `image: IMAGE` (the processed result), and returns
**one `LC_PIPE` output**. It is a non-output node and doesn't force
an otherwise bypassed lazy branch.

```text
MR Lazy Detailer 1 → MR Lazy Detailer 2 → MR Lazy Detailer 3
                                                │ LC_PIPE
                                                ▼
                                            LC Pipe Out
                                            │         │
                                            │ pipe    └─ IMAGE → SEGS Detailer ── IMAGE ─┐
                                            │                                          │
                                            ▼                                          ▼
                                          MR Pipe Image Replace (Preserve Protection)
                                                               │ LC_PIPE
                                                               ▼
                                                       Final MR Lazy Detailer
```

**Connect `LC Pipe Out.pipe` to the MR node's `pipe` and the output
image from SEGS to its `image` input.** The separate LC Pipe Out
`protect_mask` output and the SEGS mask output are **not needed**.
The SEGS edit does not contribute any new protection; only the masks
from prior LC detailers are retained. The final LC/MR detailer then
merges its newly processed region with those existing masks.

Why this is necessary: LC MaskMaker stores the accumulated mask under
`pipe["lc_protect"]` as both a tensor and a fingerprint of the image
it protects. LC Pipe (in/edit) preserves that dictionary but doesn't
update its fingerprint when a new image is inserted. The following
detailer therefore treats the old protection as stale and uses only
its own mask. The MR replacement node:

1. Verifies the existing pipe's original image is well formed.
2. Verifies the original protection fingerprint is **valid for the
   original image** (refuses to revive a preexisting stale mask).
3. Validates that the updated image has **identical batch, dimensions,
   and channels**, and the old mask exactly matches batch/height/width.
4. Copies the pipe, substitutes the processed image, and updates only
   the protection fingerprint using **LoneCat's exact fingerprint
   calculation**. The accumulated mask tensor and its pixels are unchanged.
5. Removes `lc_found` (cached SAM3 finds for the previous image);
   fresh detections can be computed as needed. All other pipe settings
   remain unchanged.

If the incoming pipe has **no previous protection mask**, image
replacement still works normally. If the SEGS stage resizes the image,
changes batch size, moves the subject substantially, or produces a stale
original mask, the safe approach is to reject the replacement or to
realign the mask separately—not to retag it blindly.

### Wiring with KJ Lazy Switch

For a stage controlled by a `no-face` tag:

```text
Get LC_PIPE from previous stage ───────────────┐
           │                                   │
           ▼                                   ▼
 MR Lazy Smart Detailer (pipe)               on_true
           │
           ├─ IMAGE ───────> MR Conditional Preview Sink.image_1
           ├─ MASK ────────> MR Conditional Preview Sink.mask_1
           │
           ▼
 MR VRAM Cache Clear (Inline)  [optional]
           │
           ▼
       on_false
           ├──────────► Lazy Switch KJ ──────► next LC pipe detailer
 JSON Tag Checker(has_tag: no-face) ── switch
           └──────────► MR Conditional Preview Sink.bypass
```

**KJ Lazy Switch:**
- `switch=true` / tag `no-face`: `on_true` (the original input LC_PIPE).
- `switch=false`: `on_false` (the processed output LC_PIPE).

**MR Conditional Preview Sink:**
- `bypass` must be connected to the **same** tag Boolean as the KJ switch.
- Optional lazy inputs: `image_1`, `image_2`, `mask_1`, `mask_2`.
- `bypass=true` requests **none** of the image/mask previews, reports SKIPPED.
- `bypass=false` requests only the **connected** preview inputs, then reports
  SELECTED and displays their resized temp PNGs.
- The preview UI status light indicates **selected vs skipped**; a selected
  detailer might have used ComfyUI cache rather than rerunning diffusion.
  It does not claim that a model was freshly executed.
- The sink is intentionally `OUTPUT_NODE=True` so that SKIPPED can be shown
  for every queued image. Its preview inputs are lazy, so this does not force
  the bypassed detailer branch. It is an independent **conditional** output.

The MR pipe detailers are **non-output nodes**, even though the LoneCat
originals are independent outputs. The MR adapters delegate the entire
execution to the actual installed LoneCat Python classes at runtime; they
retain its LC_PIPE updated image, protect mask, SAM3 hits, IMAGE/MASK outputs,
and internal preview UI. The adapters add an `images` UI alias for the
processed result to support the stock ComfyUI preview renderer.

**Important: avoid any independent output roots inside the lazy branch.**
LoneCat's existing **LC Preview Image**, **LC Preview Mask**, and **LC VRAM
Cache Clear** are marked `OUTPUT_NODE=True`. A standalone node of those types
connected to an MR detailer result can still force the detailer to execute,
regardless of the KJ switch. Replace with **MR Conditional Preview Sink**
for mask/image preview and **MR VRAM Cache Clear (Inline)** for cleanup.
The older Image-Utils inline preview nodes are also safe, provided their
passthrough IMAGE is consumed by the selected branch.

**Load order and safety:** Image-Utils does not import LoneCat at package
import time. The adapters resolve the original ComfyUI node IDs when their
schema is requested and on execution. If LoneCat is missing, no other Image
Utils node is affected and the MR adapter raises an actionable error if used.
The adapter validates that upstream still exposes `LC_PIPE, IMAGE, MASK` and
an LC_PIPE input, and uses an upstream class instance for its normal detail
logic. If a LoneCat update changes the interface, update the adapter.

**Testing:** Unit tests mock LoneCat and exercise schema resolution,
pipe-result preservation, skip/active lazy input requests, preview writes,
and inline VRAM pass-through. GPU execution and the actual classic/Nodes 2.0
frontend still require verification on your ComfyUI instance.

### Suggested smoke test

1. Upgrade both Image-Utils and LoneCat, restart ComfyUI.
2. Add an **MR Lazy Smart Detailer (pipe)** and a **KJ Lazy Switch** with the
   incoming pipe wired to `on_true`, MR processed pipe to `on_false`.
3. Wire `no-face` into both `switch` and **MR Conditional Preview Sink.bypass**.
4. Wire MR detailer IMAGE and MASK outputs into the preview sink's image/mask
   inputs. Use MR inline VRAM-clear if desired.
5. Queue an image with `no-face`. Check the sink is SKIPPED, the MR
   detailer does not run, and the original LC pipe reaches the next stage.
6. Queue one without `no-face`. Check the detailer runs (or is cached)
   and the pipe image/protect masks reach the next stage.

If an MR detailer still runs on a bypassed image, look for extra output roots
connected to that branch, including LC Preview Mask and older VRAM-clear
nodes.
