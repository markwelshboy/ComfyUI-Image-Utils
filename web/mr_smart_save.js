/** Friendly token picker + preview for Image Utils Save Image + Sidecar.
 *
 * Static preview uses visible widgets. When source_name or metadata comes from
 * a connected input, only the backend knows its exact value: the node then
 * shows the last actual save path rather than pretending to know it in advance.
 */
import { app } from "../../scripts/app.js";

// ComfyUI historically saved widgets_values by position. Adding widgets (or
// converting one into an input) could silently shift values on load. Preserve a
// named snapshot alongside the standard ComfyUI data, without changing widget
// positions or adding serializable fields. Recent frontends also provide
// widgets_values_named; older frontends use our node.properties fallback.
const SAVER_SNAPSHOT_KEY = "mr_smart_save_named_values";
const SAVER_SNAPSHOT_VERSION = 1;
const SAVER_FIELDS = [
  "filename_prefix", "include_current_workflow_in_history", "source_name",
  "filename_template", "output_directory", "stage", "tracking_id",
  "counter_padding", "counter_start", "collision_policy", "seed",
  "negative_prompt", "model_name", "settings_json",
];
const SAVER_DEFAULTS = Object.freeze({
  source_name: "", output_directory: "", stage: "detailer-pipe",
  tracking_id: "", counter_padding: 4, counter_start: 0,
  collision_policy: "append_revision", seed: -1,
  negative_prompt: "", model_name: "", settings_json: "{}",
});
const SAVER_REPAIR_FIELDS = Object.keys(SAVER_DEFAULTS);
const SAVER_COLLISION_OPTIONS = ["append_revision","error","increment_counter"];

function saverValid(name, value) {
  if (["filename_prefix", "source_name", "filename_template",
       "output_directory", "stage", "model_name", "negative_prompt"].includes(name))
    return typeof value === "string" && (name !== "stage" || !!value.trim());
  if (name === "tracking_id")
    return typeof value === "string" && (!value || /^\d{1,16}$/.test(value));
  if (name === "include_current_workflow_in_history") return typeof value === "boolean";
  if (name === "counter_padding")
    return Number.isSafeInteger(value) && value >= 1 && value <= 12;
  if (name === "counter_start")
    return Number.isSafeInteger(value) && value >= 0 && value <= 999999999;
  if (name === "seed")
    return Number.isSafeInteger(value) && value >= -1;
  if (name === "collision_policy") return SAVER_COLLISION_OPTIONS.includes(value);
  if (name === "settings_json") {
    if (typeof value !== "string") return false;
    try { return JSON.parse(value || "{}") instanceof Object &&
                 !Array.isArray(JSON.parse(value || "{}")); }
    catch { return false; }
  }
  return false;
}

function saverNamedValues(node) {
  const values = {};
  for (const name of SAVER_FIELDS) {
    const widget = findWidget(node, name);
    if (widget && widget.serialize !== false && saverValid(name, widget.value))
      values[name] = widget.value;
  }
  return values;
}
function saverIssues(node) {
  const bad = SAVER_FIELDS.filter(name => {
    const widget = findWidget(node, name);
    return widget && widget.serialize !== false && !saverValid(name,widget.value);
  });
  // Common legacy shift: stage ended up in the output folder, tracking ID
  // received counter padding, counter padding received counter start, etc.
  // Other fields may still look valid; never guess their intended values.
  return bad;
}
function saverRestoreNamed(node, data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return [];
  const restored = [];
  for (const name of SAVER_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(data, name)) continue;
    const widget = findWidget(node, name);
    if (!widget || widget.serialize === false || !saverValid(name,data[name])) continue;
    widget.value = data[name];
    restored.push(name);
  }
  return restored;
}

function saverApplyRepair(node) {
  for (const name of SAVER_REPAIR_FIELDS) {
    const widget = findWidget(node,name);
    if (!widget) continue; // Connected widgets are controlled by the graph.
    widget.value = SAVER_DEFAULTS[name];
    widget.callback?.(widget.value);
  }
  node.__mrSmartSaveLegacy = false;
  node.__mrSmartSaveReviewNote = "Advanced fields reset. Check the output directory, " +
    "stage and tracking ID before queuing; save the workflow to store values by name.";
  node.__mrSmartSaveRefresh?.();
  node.setDirtyCanvas?.(true,true);
}

// Textarea widgets don't render their names in ComfyUI's canvas. Put a
// persistent, legible heading inside each existing textarea, above its actual
// content, WITHOUT inserting extra widgets (which could shift old workflows).
function saverLabelTextarea(node, name, title, placeholder) {
  const widget = findWidget(node,name);
  const input = widget?.element ?? widget?.inputEl;
  if (!input || typeof input.setAttribute !== "function") return false;
  input.setAttribute("aria-label",title);
  input.setAttribute("title",title);
  input.setAttribute("placeholder",placeholder);
  // Static SVG CSS background keeps the label visible even for settings_json
  // whose default value is {}. No new widget or content is serialized.
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="355" height="25">' +
    '<text x="5" y="17" fill="#edb979" font-size="12" ' +
    'font-family="Arial, sans-serif" font-weight="bold">' + title + '</text></svg>';
  const style=input.style;
  if (style) {
    style.backgroundImage = "url('data:image/svg+xml," + encodeURIComponent(svg) + "')";
    style.backgroundRepeat = "no-repeat";
    style.backgroundPosition = "8px 4px";
    style.backgroundSize = "auto 25px";
    style.paddingTop = "32px";
    style.boxSizing = "border-box";
  }
  return true;
}

const TOKENS = [
  ["Filename prefix", "%prefix%"],
  ["Input name", "%input_name%"],
  ["Tracked count", "%tracked_count%"],
  ["Aligned count", "%aligned_counter%"],
  ["Output counter", "%counter%"],
  ["Seed", "%seed%"],
  ["Date", "%date%"],
  ["Time", "%time%"],
  ["Batch", "%batch%"],
  ["Stage", "%stage%"],
];

function findWidget(node, name) {
  return node.widgets?.find(widget => widget.name === name);
}

function templatePreview(node) {
  const field = name => findWidget(node, name)?.value;
  const template = String(field("filename_template") ?? "").trim();
  if (!template) return "Legacy filename mode: " + String(field("filename_prefix") || "ImageUtils") + "_00001_.png";
  const sourceName = String(field("source_name") || "").replaceAll("\\", "/");
  const rawName = sourceName.split("/").at(-1).replace(/\.[^.]+$/, "") || "image";
  const match = rawName.match(/(?:^|[_\-\s])(\d+)$/);
  const tracked = match ? match[1] : "0000";
  const pad = Math.max(1,Math.min(12,Number(field("counter_padding")) || 4));
  const now = new Date();
  const date = [now.getFullYear(),String(now.getMonth()+1).padStart(2,"0"),String(now.getDate()).padStart(2,"0")].join("-");
  const time = [now.getHours(),now.getMinutes(),now.getSeconds()].map(x=>String(x).padStart(2,"0")).join("");
  const prefix = String(field("filename_prefix") || "ImageUtils")
    .replaceAll("\\", "/").split("/").at(-1).trim();
  const values = {
    prefix,
    input_name: rawName,
    tracked_count: tracked.padStart(pad,"0"),
    aligned_counter: tracked.padStart(pad,"0"),
    counter: String(Number(field("counter_start")) || 0).padStart(pad,"0"),
    seed: Number(field("seed")) >= 0 ? String(field("seed")) : "unknown",
    date,time,batch:"000",stage:String(field("stage") || "processed"),
  };
  let output = template.replace(/%([^%]+)%/g,(token,key)=>values[key] ?? token);
  if (!output.endsWith(".png")) output += ".png";
  const directory = String(field("output_directory") || "").trim() || "(ComfyUI output)";
  // Connected inputs and sidecar origin IDs may override the widget preview.
  const connected = node.inputs?.some(i=>i.link!=null &&
    ["source_name","sidecar_json","tracking_id","output_directory","seed"].includes(i.name));
  return directory.replace(/\/$/,"") + "/" + output +
    (connected ? "  · estimate; linked inputs may change this" : "  · estimated") +
    (template.includes("%prefix%") ? "" :
     "  · filename_prefix omitted; insert %prefix% to include it");
}

function addLabel(text, style="") {
  const element = document.createElement("div");
  element.textContent = text;
  element.style.cssText = style || "font:11px sans-serif;color:#b7c5cb;overflow-wrap:anywhere;";
  return element;
}

app.registerExtension({
  name: "ImageUtils.MRSmartSaveFilenameUI",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "ImageUtilsSaveImageWithSidecar") return;
    const oldCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const response = oldCreated?.apply(this, arguments);
      try {
        const root = document.createElement("div");
        root.style.cssText = "font:11px sans-serif;padding:9px 10px;border-radius:7px;border:1px solid #47525b;background:#181e23;color:#c7d7df;display:flex;flex-direction:column;gap:6px;";
        const header = addLabel("FILENAME TEMPLATE · quick insert", "font:bold 11px sans-serif;color:#e4b884;");
        const buttons = document.createElement("div");
        buttons.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;";
        for (const [name, token] of TOKENS) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = "+" + name;
          button.title = "Insert " + token + " into filename_template";
          button.style.cssText = "border:1px solid #45545e;background:#2b363f;color:#d3e1ea;border-radius:4px;padding:4px 6px;cursor:pointer;font:10px sans-serif;";
          button.addEventListener("click",event=>{
            event.preventDefault();
            event.stopPropagation();
            const widget=findWidget(this,"filename_template");
            if(!widget) return;
            const old=String(widget.value || "");
            widget.value=old + token;
            widget.callback?.(widget.value);
            this.__mrSmartSaveRefresh?.();
            this.setDirtyCanvas?.(true,true);
          });
          buttons.append(button);
        }
        const label = addLabel("WILL SAVE AS", "font:bold 11px sans-serif;color:#ecb06c;");
        const preview = addLabel("", "font:11px monospace;white-space:pre-wrap;color:#9bd2aa;overflow-wrap:anywhere;");
        const last = addLabel("Last save: not run yet", "font:10px sans-serif;color:#abb9c5;overflow-wrap:anywhere;");
        root.append(header,buttons,label,preview,last);
        this.addDOMWidget("mr_filename_preview","MR_FILENAME_PREVIEW",root,{
          serialize:false,getMinHeight:()=>132,getMaxHeight:()=>172
        });
        this.__mrSmartSaveRefresh = () => {
          const updated = templatePreview(this);
          if(preview.textContent !== updated) preview.textContent=updated;
        };
        this.__mrSavedLastLabel=last;
        this.__mrSmartSaveRefresh();
        // The widgets can be replaced by sockets when connected; the execution
        // result remains authoritative in those cases.
        const oldDraw=this.onDrawForeground;
        this.onDrawForeground=function() {
          oldDraw?.apply(this,arguments);
          this.__mrSmartSaveRefresh?.();
        };
      }catch(error){
        console.warn("[Image Utils] Smart Save preview unavailable",error);
      }
      return response;
    };
    const oldExecuted=nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted=function(message) {
      const result=oldExecuted?.apply(this,arguments);
      const paths=message?.mr_saved_paths || [];
      if(paths.length && this.__mrSavedLastLabel){
        this.__mrSavedLastLabel.textContent="Last save: "+paths.join(" · ");
      }
      this.__mrSmartSaveRefresh?.();
      return result;
    };
  },
});
