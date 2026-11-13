/** On-node status indicator for MR Conditional Preview Sink.
 * A green light means the detailer path was selected (possibly cached);
 * grey means skipped. It deliberately does NOT misrepresent cache hits as
 * fresh model execution. Standard ComfyUI IMAGE previews remain available.
 */
import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "ImageUtils.MRConditionalPreviewStatus",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "ImageUtilsMRConditionalPreviewSink") return;

    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      try {
        const wrap = document.createElement("div");
        wrap.style.cssText = "display:flex;align-items:center;gap:8px;height:30px;padding:2px 8px;font:12px sans-serif;";
        const lamp = document.createElement("span");
        lamp.style.cssText = "display:inline-block;width:11px;height:11px;border-radius:50%;background:#777;flex:none;";
        const caption = document.createElement("span");
        caption.textContent = "NOT RUN";
        wrap.append(lamp, caption);
        this.addDOMWidget("mr_preview_status", "MR_STATUS", wrap, {
          serialize: false,
          getMinHeight: () => 30,
          getMaxHeight: () => 30,
        });
        this.__mrStatusLamp = lamp;
        this.__mrStatusCaption = caption;
      } catch (e) {
        console.warn("[Image Utils] MR status widget unavailable", e);
      }
      return result;
    };

    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = executed?.apply(this, arguments);
      const status = message?.mr_preview_status?.[0];
      if (status) {
        const stage = String(status.stage || "Stage");
        const skipped = status.state === "skipped";
        const noPreview = status.state === "no-previews";
        const caption = skipped ? "SKIPPED" : noPreview ? "SELECTED · no preview inputs" : "SELECTED · previewed";
        if (this.__mrStatusLamp) {
          this.__mrStatusLamp.style.background = skipped ? "#777" : noPreview ? "#bd8c2e" : "#23845c";
        }
        if (this.__mrStatusCaption) {
          this.__mrStatusCaption.textContent = stage + ": " + caption;
          this.__mrStatusCaption.title = "Selected may be executed or reused from ComfyUI cache.";
        }
        this.setDirtyCanvas?.(true, true);
      }
      return result;
    };
  },
});
