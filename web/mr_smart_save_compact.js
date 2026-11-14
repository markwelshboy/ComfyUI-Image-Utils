/* Compact frontend for Image Utils · Save Image + Sidecar.
 * The original ComfyUI widgets stay in the node's widget array and continue
 * to serialize and execute normally. Only their canvas presentation is hidden.
 */
export const UI_SETTINGS_KEY = "mr_saver_ui";
const DEFAULT_PREFS={previewHeight:340,settingsOpen:false};
const CSS=[
".mr-saver{display:flex;flex-direction:column;gap:9px;color:#dbe7ed;background:#162027;border:1px solid #455765;border-radius:8px;padding:10px;font:12px system-ui,sans-serif;box-sizing:border-box;width:100%}",
".mr-saver *{box-sizing:border-box}.mr-saver [hidden]{display:none!important}",
".mr-saver button{border:1px solid #455e6e;background:#2d3e49;color:#ecf2f6;border-radius:5px;padding:5px 8px;cursor:pointer;font:11px system-ui,sans-serif}",
".mr-saver button:hover{background:#405866}.mr-saver button:disabled{opacity:.5;cursor:not-allowed}",
".mr-saver .toolbar{display:flex;align-items:center;gap:6px}.mr-saver .grow{flex:1}",
".mr-saver .chip{border:1px solid #4c795f;color:#b8dfc8;background:#1b3426;padding:4px 7px;border-radius:5px;font-size:10px}",
".mr-saver .settings{background:#1c2a33;border:1px solid #3d5260;padding:10px;border-radius:7px;overflow:auto;max-height:340px;display:flex;flex-direction:column;gap:9px}",
".mr-saver .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}",
".mr-saver .field{display:flex;flex-direction:column;gap:3px;min-width:0}.mr-saver .wide{grid-column:span 2}",
".mr-saver .field>label{color:#b1c4ce;font:10px system-ui,sans-serif}",
".mr-saver input:not([type=checkbox]),.mr-saver textarea,.mr-saver select{width:100%;background:#0f1821;color:#ebf2f6;border:1px solid #506472;border-radius:5px;min-height:27px;padding:5px 6px;font:12px system-ui,sans-serif}",
".mr-saver input:focus,.mr-saver textarea:focus{outline:1px solid #d6ac72}.mr-saver .check{display:flex;gap:8px;align-items:center}",
".mr-saver .locked{color:#e9bc8a;font-size:10px}.mr-saver .tokens{display:flex;flex-wrap:wrap;gap:4px}",
".mr-saver .tokens button{font-size:10px;padding:3px 5px}",
".mr-saver .heading{color:#e5b881;font:bold 10px system-ui,sans-serif}",
".mr-saver .estimate{padding:6px;background:#111a20;color:#b4dfc7;border:1px solid #3b4e56;border-radius:5px;font:11px ui-monospace,monospace;overflow-wrap:anywhere;white-space:pre-wrap}",
".mr-saver details{border-top:1px solid #3b505e;padding-top:7px}.mr-saver summary{color:#e0b782;cursor:pointer;font-size:11px}",
".mr-saver .preview{display:flex;justify-content:center;align-items:center;overflow:hidden;position:relative;background:#0b0e14;border:1px solid #3b4a56;border-radius:7px}",
".mr-saver .preview img{width:100%;height:100%;object-fit:contain;cursor:zoom-in;display:block}",
".mr-saver .placeholder{padding:15px;color:#96a6b1;text-align:center;font-size:11px}",
".mr-saver .last{overflow-wrap:anywhere;color:#b9cad3;font-size:11px;line-height:1.4}",
".mr-saver .nav{display:flex;justify-content:center;gap:9px;align-items:center}",
".mr-saver .warn{color:#ffdaad;background:#503324;border:1px solid #ab7045;padding:7px;border-radius:5px;line-height:1.5}",
".mr-saver .repair{background:#694327;border-color:#cc9761}",
".mr-saver-prefs,.mr-saver-zoom{border:1px solid #617482;background:#1e2b34;color:#e5edf2;border-radius:9px;padding:15px;max-height:90vh;overflow:auto;font:12px system-ui,sans-serif}",
".mr-saver-prefs{width:min(90vw,380px)}.mr-saver-zoom{width:min(94vw,1300px);max-width:94vw}",
".mr-saver-prefs::backdrop,.mr-saver-zoom::backdrop{background:#000c}",
".mr-saver-prefs input[type=range]{width:100%;margin:10px 0}.mr-saver-zoom img{width:100%;max-height:82vh;object-fit:contain}",
].join("\n");

function make(tag,cls="",label=""){
 const e=document.createElement(tag);if(cls)e.className=cls;
 if(label)e.textContent=label;return e;
}
function button(label,cb){
 const b=make("button","",label);b.type="button";
 b.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();cb();});return b;
}
function prefValues(raw){
 const p=raw&&typeof raw==="object"&&!Array.isArray(raw)?raw:{};
 const h=Number(p.previewHeight);
 return {previewHeight:Number.isFinite(h)?Math.max(200,Math.min(650,Math.round(h))):340,
  settingsOpen:typeof p.settingsOpen==="boolean"?p.settingsOpen:false};
}
function savePrefs(node,prefs){
 node.properties ||= {};
 node.properties[UI_SETTINGS_KEY]={...prefs};
 node.setDirtyCanvas?.(true,true);
}
function connected(node,name){
 return !!node.inputs?.some(i=>i.name===name&&i.link!=null);
}
function hideRawWidgets(node, names){
 for(const name of names){
  const w=node.widgets?.find(x=>x.name===name);
  if(!w)continue;
  w.__mrSaverHidden=true;
  w.hidden=true;
  // Do not remove widgets from node.widgets: they own prompt values and
  // positional serialization for old workflows.
  w.type="hidden";w.computeSize=()=>[0,-4];
  if(w.element?.style)w.element.style.display="none";
  if(w.inputEl?.style)w.inputEl.style.display="none";
 }
}
function imageURL(api,record){
 if(!record||record.available===false||!record.filename)return "";
 const suffix="/view?filename="+encodeURIComponent(record.filename)+
  "&subfolder="+encodeURIComponent(record.subfolder||"")+
  "&type="+encodeURIComponent(record.type||"output")+"&preview=webp";
 return typeof api?.apiURL==="function"?api.apiURL(suffix):suffix;
}
export function buildSaverUI(node,api,options){
 const {field,fieldNames,tokens,estimateText,issues,repair}=options;
 const prefs=prefValues(node.properties?.[UI_SETTINGS_KEY]);
 const root=make("div","mr-saver");
 const style=make("style");style.textContent=CSS;root.append(style);
 const toolbar=make("div","toolbar");
 const expand=button("▾ Settings",()=>toggle(!prefs.settingsOpen));
 const gear=button("⚙",showPreferences);gear.title="Layout preferences saved with this workflow";
 toolbar.append(expand,gear,make("div","grow"),make("span","chip","PNG + sidecar"));
 root.append(toolbar);
 const settings=make("div","settings");
 const fields=new Map();
 function addField(name,title,type="text",wide=false){
  const box=make("div","field"+(wide?" wide":""));
  const label=make("label","",title);
  const input=make(type==="select"?"select":type==="textarea"?"textarea":"input");
  if(type==="number")input.type="number";
  else if(type==="checkbox")input.type="checkbox";
  else if(type!=="select"&&type!=="textarea")input.type="text";
  if(type==="select"){
   for(const v of ["append_revision","error","increment_counter"]){
    const opt=make("option","",v);opt.value=v;input.append(opt);
   }
  }
  if(type==="textarea")input.rows=name==="settings_json"?3:2;
  input.setAttribute("aria-label",title);
  const lock=make("small","locked","Connected socket controls this field");lock.hidden=true;
  if(type==="checkbox"){label.className="check";label.prepend(input);box.append(label,lock);}
  else box.append(label,input,lock);
  fields.set(name,{input,lock});
  input.addEventListener(type==="select"||type==="checkbox"?"change":"input",()=>{
   if(connected(node,name))return;
   const w=field(node,name);if(!w)return;
   const value=type==="checkbox"?input.checked:
    type==="number"?(input.value.trim()===""?NaN:Number(input.value)):input.value;
   w.value=value;w.callback?.(value);
   node.setDirtyCanvas?.(true,true);
   refresh();
  });
  return box;
 }
 settings.append(make("div","heading","OUTPUT & NAMING"));
 const names=make("div","grid");
 names.append(addField("filename_prefix","Filename prefix"),
  addField("output_directory","Save directory"),
  addField("source_name","Source file / original filename","text",true),
  addField("filename_template","Filename template","text",true));
 settings.append(names);
 const tokenBar=make("div","tokens");
 for(const [label,token] of tokens){
  tokenBar.append(button("+"+label,()=>{
   if(connected(node,"filename_template"))return;
   const input=fields.get("filename_template").input;
   input.value+=token;
   input.dispatchEvent(new Event("input",{bubbles:true}));
  }));
 }
 settings.append(tokenBar,make("div","heading","WILL SAVE AS"));
 const estimate=make("div","estimate");settings.append(estimate);
 settings.append(make("div","heading","PROCESSING & COUNTERS"));
 const counts=make("div","grid");
 counts.append(addField("stage","Processing stage"),addField("tracking_id","Tracking ID"),
  addField("counter_padding","Counter digits","number"),
  addField("counter_start","Starting counter","number"),
  addField("collision_policy","If file exists","select",true));
 settings.append(counts);
 const advanced=make("details");advanced.append(make("summary","","PROVENANCE / ADVANCED"));
 const more=make("div","grid");
 more.append(addField("seed","Seed","number"),addField("model_name","Model name"),
  addField("include_current_workflow_in_history","Store workflow in sidecar history","checkbox",true),
  addField("negative_prompt","Negative prompt (optional)","textarea",true),
  addField("settings_json","Generation settings (JSON)","textarea",true));
 advanced.append(more,make("p","","Connected sidecar_json and positive_prompt sockets take precedence over empty generation fields."));
 settings.append(advanced);
 root.append(settings);
 const frame=make("div","preview");
 const image=make("img");image.alt="Saved image preview";image.hidden=true;
 const placeholder=make("div","placeholder","Run the workflow to save and preview the result here");
 frame.append(image,placeholder);
 const nav=make("div","nav");nav.hidden=true;
 const prev=button("‹",()=>show(current-1));
 const next=button("›",()=>show(current+1));
 const page=make("span","","1 / 1");nav.append(prev,page,next);
 const last=make("div","last","Last save: not run yet");
 root.append(frame,nav,last);
 const warning=make("div","warn");warning.hidden=true;
 const reset=button("Reset misaligned advanced settings",()=>{
  if(!window.confirm("Reset optional saver settings?\n\nThis keeps filename prefix, template and connections. Review output directory, stage and tracking ID before queuing."))return;
  repair(node);refresh();
 });
 reset.className="repair";reset.hidden=true;
 root.append(warning,reset);
 let previews=[],current=0,dialog=null,prefsDialog=null;
 function show(index){
  if(!previews.length)return;
  current=(index+previews.length)%previews.length;
  const url=imageURL(api,previews[current]);
  if(url){
   image.hidden=false;placeholder.hidden=true;
   image.src=url+"&_="+Date.now();
  }else{
   image.hidden=true;placeholder.hidden=false;
   placeholder.textContent="Image saved. Preview unavailable for this directory.";
  }
  nav.hidden=previews.length<2;
  page.textContent=(current+1)+" / "+previews.length;
 }
 image.addEventListener("error",()=>{
  image.hidden=true;placeholder.hidden=false;
  placeholder.textContent="Preview could not be loaded. The image is still saved.";
 });
 image.addEventListener("click",()=>{
  if(!image.src||!document.body?.appendChild)return;
  dialog=make("dialog","mr-saver-zoom");
  dialog.append(button("Close ×",()=>dialog.close()));
  const large=make("img");large.alt="Enlarged saved image";large.src=image.src;
  dialog.append(large);document.body.appendChild(dialog);
  dialog.addEventListener("close",()=>{dialog.remove();dialog=null;},{once:true});
  dialog.showModal();
 });
 function applyLayout(resize=false){
  settings.hidden=!prefs.settingsOpen;
  expand.textContent=(prefs.settingsOpen?"▴":"▾")+" Settings";
  frame.style.height=prefs.previewHeight+"px";
  if(resize && Array.isArray(node.size)){
   const width=Math.max(440,node.size[0]);
   const height=prefs.previewHeight+(prefs.settingsOpen?490:155);
   node.setSize?.([width,height]);node.setDirtyCanvas?.(true,true);
  }
 }
 function toggle(open){
  prefs.settingsOpen=!!open;savePrefs(node,prefs);applyLayout(true);refresh();
 }
 function showPreferences(){
  prefsDialog=make("dialog","mr-saver-prefs");
  prefsDialog.append(make("h3","","Save Image preferences"));
  const text=make("div","","Preview height: "+prefs.previewHeight+" px");
  const slider=make("input");slider.type="range";slider.min="200";slider.max="650";
  slider.step="10";slider.value=String(prefs.previewHeight);
  slider.addEventListener("input",()=>{
   prefs.previewHeight=Number(slider.value);
   text.textContent="Preview height: "+prefs.previewHeight+" px";
   savePrefs(node,prefs);applyLayout(true);
  });
  const keep=make("label","","Keep settings expanded");
  const check=make("input");check.type="checkbox";check.checked=prefs.settingsOpen;
  keep.prepend(check);
  check.addEventListener("change",()=>toggle(check.checked));
  prefsDialog.append(text,slider,keep,
   make("p","","Preferences are saved with this workflow. Output settings remain editable in the node."),
   button("Done",()=>prefsDialog.close()));
  document.body.appendChild(prefsDialog);
  prefsDialog.addEventListener("close",()=>{prefsDialog.remove();prefsDialog=null;},{once:true});
  prefsDialog.showModal();
 }
 function refresh(){
  for(const [name,{input,lock}] of fields){
   const w=field(node,name);
   const linked=connected(node,name);
   input.disabled=!w||linked;lock.hidden=!linked;
   if(!w||document.activeElement===input)continue;
   if(input.type==="checkbox")input.checked=!!w.value;
   else if(String(input.value)!==String(w.value??""))input.value=String(w.value??"");
  }
  estimate.textContent=estimateText(node);
  const bad=issues(node);
  const trouble=bad.length>0||node.__mrSmartSaveNeedsReview;
  let msg=node.__mrSmartSaveReviewNote||"";
  if(bad.length)msg="⚠ Invalid/shifted widget values: "+bad.join(", ")+
    ". Other fields may have shifted. Check directory, stage, tracking ID.";
  else if(trouble)msg="⚠ Older invalid settings. Review them before queuing.";
  else if(node.__mrSmartSaveLegacy)msg="Older positional workflow: verify directory, stage and tracking ID before saving.";
  warning.hidden=!msg;warning.textContent=msg;reset.hidden=!trouble;
 }
 function applyStoredPrefs(){
  Object.assign(prefs,prefValues(node.properties?.[UI_SETTINGS_KEY]));
  applyLayout(true);refresh();
 }
 function updatePreview(message){
  previews=Array.isArray(message?.mr_saved_preview)&&message.mr_saved_preview.length?
   message.mr_saved_preview:Array.isArray(message?.images)?message.images:[];
  const paths=Array.isArray(message?.mr_saved_paths)?message.mr_saved_paths:[];
  if(paths.length){last.textContent="✓ Saved: "+paths.at(-1);last.title=paths.join("\n");}
  if(previews.length)show(previews.length-1);
  else if(paths.length){
   image.hidden=true;placeholder.hidden=false;
   placeholder.textContent="Saved successfully; no browser preview returned.";
  }
 }
 hideRawWidgets(node,fieldNames);
 const helper=node.addDOMWidget("mr_filename_preview","MR_FILENAME_PREVIEW",root,{
  serialize:false,
  getMinHeight:()=>prefs.previewHeight+(prefs.settingsOpen?485:0)+145,
  getMaxHeight:()=>prefs.previewHeight+(prefs.settingsOpen?510:0)+185,
 });
 if(helper)helper.serialize=false;
 applyLayout(true);refresh();
 return {root,refresh,updatePreview,applyStoredPrefs,warning,reset,last,
  get prefs(){return {...prefs};},
  close(){dialog?.close();prefsDialog?.close();}
 };
}
