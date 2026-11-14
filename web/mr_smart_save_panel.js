/** Compact, reactive ComfyUI saver UI.
 * The existing native widgets are retained (hidden on canvas) as the sole
 * source of workflow values. This view never creates serializable widgets.
 */
const UI_PREFS_KEY="mr.image_utils.saver_ui.v1";
const DEFAULTS={previewHeight:340,collapsed:true,compact:true};
const BLOCKS=[
 ["NAMING",[["filename_prefix","Filename prefix"],["filename_template","Filename template"],["source_name","Source image name"]]],
 ["OUTPUT",[["output_directory","Output directory"],["stage","Processing stage"],["tracking_id","Tracking ID (optional)"]]],
 ["COUNTERS",[["counter_padding","Counter padding"],["counter_start","Start counter"],["collision_policy","On collision"]]],
 ["PROVENANCE",[["include_current_workflow_in_history","Include workflow in history"],["seed","Original seed"],["model_name","Model name"]]],
 ["ADVANCED METADATA",[["negative_prompt","Negative prompt (optional)"],["settings_json","Generation settings JSON"]]],
];
const NUMBERS=new Set(["counter_padding","counter_start","seed"]);
export const SAVE_WIDGET_NAMES=BLOCKS.flatMap(item=>item[1].map(field=>field[0]));

function prefsLoad(){
  try{
    const value=JSON.parse(localStorage.getItem(UI_PREFS_KEY)||"{}");
    const h=Number(value.previewHeight);
    return {previewHeight:Number.isFinite(h)?Math.max(180,Math.min(700,h)):340,
      collapsed:value.collapsed!==false,compact:value.compact!==false};
  }catch{return {...DEFAULTS};}
}
function prefsSave(p){try{localStorage.setItem(UI_PREFS_KEY,JSON.stringify(p));}catch{}}
function el(tag,txt,style){
  const x=document.createElement(tag);
  if(txt!==undefined&&txt!==null)x.textContent=txt;
  if(style)x.style.cssText=style;
  return x;
}
function btn(text,title,callback){
  const b=el("button",text,"background:#2b3942;color:#e6e9eb;border:1px solid #51636c;"+
    "border-radius:5px;padding:5px 9px;font:11px system-ui;cursor:pointer;");
  b.type="button";b.title=title||text;
  b.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();callback();});
  return b;
}
const row=()=>el("div",null,"display:flex;align-items:center;gap:6px;flex-wrap:wrap;");
const label=(name)=>el("label",name,"font:11px system-ui;color:#bfcfd7;line-height:1.3;");
function chooser(node,name,find,refresh){
  const native=find(node,name);if(!native)return null;
  let c;
  if(name==="collision_policy"){
    c=el("select");
    for(const v of ["append_revision","error","increment_counter"]){
      const opt=el("option",v.replaceAll("_"," "));opt.value=v;c.append(opt);
    }
    c.value=String(native.value);
  }else if(name==="include_current_workflow_in_history"){
    c=el("input");c.type="checkbox";c.checked=!!native.value;
    c.style.cssText="width:16px;height:16px;accent-color:#da985a;";
  }else if(name==="negative_prompt"||name==="settings_json"){
    c=el("textarea");c.rows=name==="settings_json"?3:2;
    c.value=String(native.value??"");c.spellcheck=false;
    c.style.cssText="resize:vertical;min-height:55px;";
  }else{
    c=el("input");c.type=NUMBERS.has(name)?"number":"text";
    if(c.type==="number"){c.step="1";if(name==="counter_padding"){c.min=1;c.max=12;}}
    c.value=String(native.value??"");
  }
  if(c.type!=="checkbox")c.style.cssText+="background:#11191e;color:#e6edf1;"+
    "border:1px solid #50606c;border-radius:5px;width:100%;min-width:0;"+
    "padding:6px 8px;box-sizing:border-box;font:12px system-ui;";
  c.setAttribute("aria-label",name.replaceAll("_"," "));
  const write=()=>{
    const w=find(node,name);if(!w)return;
    const raw=c.type==="checkbox"?c.checked:c.value;
    w.value=NUMBERS.has(name)?(String(raw).trim()?Number(raw):NaN):raw;
    w.callback?.(w.value);
    refresh();
    node.setDirtyCanvas?.(true,true);
  };
  c.addEventListener("input",write);
  c.addEventListener("change",write);
  return c;
}
function hideNative(node,find,hidden){
  for(const name of SAVE_WIDGET_NAMES){
    const w=find(node,name);if(!w)continue;
    w.hidden=hidden;
    if((w.element||w.inputEl)?.style)
      (w.element||w.inputEl).style.display=hidden?"none":"";
  }
}
function previewUrl(preview,api){
  if(!preview?.preview_available||!preview.filename)return "";
  const qs=new URLSearchParams({filename:String(preview.filename),
    subfolder:String(preview.subfolder||""),type:String(preview.type||"output"),
    preview:"webp"});
  return api.apiURL("/view?"+qs.toString());
}
export function createSavePanel(node,{find,templatePreview,issues,repair,tokens,api}){
  const preferences=prefsLoad();
  const body=el("div",null,"display:flex;flex-direction:column;gap:8px;padding:9px;"+
    "background:#1a2229;border:1px solid #475963;color:#dfe9ed;"+
    "border-radius:8px;font:12px system-ui;box-sizing:border-box;");
  const controls={};
  const toolbar=row();
  const config=el("div",null,"border:1px solid #41525b;padding:8px;"+
    "border-radius:6px;background:#222d35;overflow-y:auto;max-height:400px;");
  const buttonToggle=btn("▸ Settings","Show naming, output and metadata controls",()=>{
    state.open=!state.open;drawLayout();
  });
  const buttonGear=btn("⚙","Preview and display preferences",()=>openPrefs());
  const format=el("span","PNG + sidecar","color:#a9bdc7;font:10px system-ui;margin-left:auto;");
  toolbar.append(buttonToggle,buttonGear,format);body.append(toolbar);
  for(const [heading,fields] of BLOCKS){
    config.append(el("div",heading,"font:600 10px system-ui;color:#e6b47c;"+
      "margin:12px 0 7px;letter-spacing:.6px;"));
    for(const [name,title] of fields){
      const c=chooser(node,name,find,refresh);
      if(!c)continue;
      controls[name]=c;
      const field=row();field.style.cssText+="align-items:center;margin:7px 0;";
      const lab=label(title);lab.style.cssText+="flex:0 0 110px;";
      const right=el("div",null,"min-width:0;flex:1;");
      right.append(c);
      if(name==="filename_template"){
        const tokensRow=row();tokensRow.style.cssText+="margin-top:6px;";
        for(const [text,token] of tokens){
          const insert=btn("+"+text,token,()=>{
            c.value=String(c.value||"")+token;
            c.dispatchEvent(new Event("input",{bubbles:true}));
          });
          insert.style.cssText+="font-size:9px;padding:3px 5px;";
          tokensRow.append(insert);
        }
        right.append(tokensRow);
      }
      field.append(lab,right);
      config.append(field);
    }
  }
  const estimate=el("div","", "font:11px monospace;color:#9adca9;"+
    "overflow-wrap:anywhere;margin:7px 0 10px;line-height:1.5;");
  config.append(el("div","WILL SAVE AS",
    "font:600 10px system-ui;color:#e6b47c;margin-top:12px;"),estimate);
  const warning=el("div","", "color:#ffdbb5;background:#493125;"+
    "border:1px solid #996d4f;border-radius:5px;padding:8px;font:11px system-ui;");
  warning.hidden=true;
  const repairButton=btn("Reset misaligned advanced settings",
    "Reset suspect values while keeping filename and connections",()=>{
      if(window.confirm("Reset advanced saver settings? Filename prefix, "+
        "template and node connections will be retained. Verify output "+
        "directory, stage and tracking ID afterward.")){
        repair(node);refresh();
      }
    });
  repairButton.hidden=true;config.append(warning,repairButton);
  body.append(config);

  const imageFrame=el("div",null,"height:340px;min-height:340px;"+
    "display:flex;flex-direction:column;justify-content:center;align-items:center;"+
    "background:#0e1318;border:1px solid #46535d;border-radius:7px;"+
    "overflow:hidden;position:relative;box-sizing:border-box;");
  const hint=el("div","Run the workflow to save and preview the result.",
    "text-align:center;color:#8aa0af;padding:18px;font:11px system-ui;");
  const img=el("img",null,"display:none;max-width:100%;max-height:100%;"+
    "width:100%;height:100%;object-fit:contain;cursor:zoom-in;");
  img.alt="Saved image preview";
  img.addEventListener("click",()=>{if(img.src)window.open(img.src,"_blank","noopener");});
  imageFrame.append(hint,img);body.append(imageFrame);

  const footer=row();
  const prev=btn("‹","Previous saved image",()=>step(-1));
  const counter=el("span","","font:10px monospace;color:#b4c3cd;");
  const next=btn("›","Next saved image",()=>step(1));
  const path=el("div","No image saved yet","font:10px system-ui;"+
    "color:#b3c7d2;overflow-wrap:anywhere;flex:1;min-width:70px;");
  footer.append(prev,counter,next,path);body.append(footer);

  const state={open:!preferences.collapsed,preferences,previews:[],index:0,
    body,config,warning,repairButton,controls,img,hint,path,
    refresh,showPreview,drawLayout};
  function step(delta){
    if(!state.previews.length)return;
    state.index=(state.index+delta+state.previews.length)%state.previews.length;
    showPreview();
  }
  function showPreview(){
    const item=state.previews[state.index];
    const hasMany=state.previews.length>1;
    prev.disabled=next.disabled=!hasMany;
    counter.textContent=state.previews.length?
      (state.index+1)+"/"+state.previews.length:"";
    path.textContent=item?.display_path?"Saved: "+item.display_path:"No image saved yet";
    const url=previewUrl(item,api);
    if(!url){
      img.style.display="none";img.removeAttribute("src");
      hint.textContent=item?
        "Saved. This destination is outside ComfyUI's served output directory; "+
        "the path is shown below.":"Run the workflow to save and preview the result.";
      hint.style.display="block";
      return;
    }
    hint.textContent="Loading image…";hint.style.display="block";
    img.style.display="none";
    img.onload=()=>{img.style.display="block";hint.style.display="none";};
    img.onerror=()=>{img.style.display="none";hint.style.display="block";
      hint.textContent="Saved, but the browser preview could not be loaded.";};
    img.src=url;
  }
  function drawLayout(){
    config.style.display=state.open?"block":"none";
    buttonToggle.textContent=state.open?"▾ Settings":"▸ Settings";
    imageFrame.style.height=preferences.previewHeight+"px";
    imageFrame.style.minHeight=preferences.previewHeight+"px";
    body.style.gap=preferences.compact?"7px":"14px";
    config.style.maxHeight=preferences.compact?"400px":"500px";
    if(node.size && node.setSize){
      node.setSize([Math.max(350,node.size[0]||350),
        preferences.previewHeight+(state.open?480:125)]);
    }
    node.setDirtyCanvas?.(true,true);
    refresh();
  }
  function refresh(){
    for(const [name,c] of Object.entries(controls)){
      const w=find(node,name);const linked=node.inputs?.some(x=>x.name===name&&x.link!=null);
      c.disabled=!!linked||!w;
      c.title=linked?"Connected input: change the upstream value":"";
      if(!w||document.activeElement===c)continue;
      if(c.type==="checkbox"){c.checked=!!w.value;continue;}
      if(w.value!==undefined&&c.value!==String(w.value))c.value=String(w.value);
    }
    estimate.textContent=templatePreview(node);
    const invalid=issues(node);
    const needs=invalid.length>0||node.__mrSmartSaveNeedsReview;
    let text=node.__mrSmartSaveReviewNote||"";
    if(invalid.length)text="⚠ Invalid/misaligned settings: "+invalid.join(", ")+
      ". Review all values before queuing.";
    else if(needs)text="⚠ Previously shifted settings: review them, then save the workflow.";
    else if(node.__mrSmartSaveLegacy)text="Older workflow: check output directory, stage "+
      "and tracking ID once, then save.";
    warning.hidden=!text;warning.textContent=text;repairButton.hidden=!needs;
  }
  function openPrefs(){
    const dlg=el("dialog",null,"background:#202b33;color:#e4edf1;"+
      "border:1px solid #60717b;border-radius:9px;"+
      "padding:18px;width:min(90vw,385px);font:12px system-ui;");
    dlg.append(el("strong","Save Image preferences",
      "display:block;font-size:15px;margin-bottom:12px;"));
    dlg.append(el("label","Preview height",
      "display:block;margin:8px 0;color:#c7d6dc;"));
    const range=el("input");range.type="range";range.min=180;range.max=700;
    range.step=20;range.value=preferences.previewHeight;range.style.width="100%";
    const size=el("span",range.value+"px","font:11px monospace;");
    range.addEventListener("input",()=>{
      preferences.previewHeight=Number(range.value);size.textContent=range.value+"px";
      prefsSave(preferences);drawLayout();
    });
    dlg.append(range,size);
    for(const [key,text] of [["collapsed","Collapse settings by default"],
                              ["compact","Compact spacing"]]){
      const wrap=el("label",null,
        "display:flex;align-items:center;gap:8px;margin:12px 0;");
      const input=el("input");input.type="checkbox";input.checked=preferences[key];
      input.addEventListener("change",()=>{
        preferences[key]=input.checked;prefsSave(preferences);drawLayout();
      });
      wrap.append(input,el("span",text));dlg.append(wrap);
    }
    dlg.append(el("p","These display preferences stay in this browser. "+
      "Filename, output directory, and metadata remain in your workflow.",
      "line-height:1.5;color:#aebfc8;"));
    dlg.append(btn("Close","Close preferences",()=>dlg.close()));
    dlg.addEventListener("close",()=>dlg.remove());
    document.body.append(dlg);dlg.showModal();
  }
  drawLayout();showPreview();
  return state;
}
export function hideSaverWidgets(node,find,hidden=true){
  hideNative(node,find,hidden);
}
