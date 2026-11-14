/** Friendly token picker + preview for Image Utils Save Image + Sidecar.
 *
 * Static preview uses visible widgets. When source_name or metadata comes from
 * a connected input, only the backend knows its exact value: the node then
 * shows the last actual save path rather than pretending to know it in advance.
 */
import { app } from "../../scripts/app.js";

const TOKENS = [
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
  const values = {
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
    (connected ? "  · estimate; linked inputs may change this" : "  · estimated");
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
