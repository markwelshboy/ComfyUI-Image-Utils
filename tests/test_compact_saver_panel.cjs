"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const filepath=path.join(__dirname,"..","web","mr_smart_save_panel.js");
const source=fs.readFileSync(filepath,"utf8")
  .replaceAll("export const ","const ")
  .replaceAll("export function ","function ")+
  "\nthis.testApi={createSavePanel,hideSaverWidgets,SAVE_WIDGET_NAMES};";

const elements=[];
class FakeElement {
  constructor(tag){
    this.tag=tag;this.style={cssText:""};this.children=[];this.listeners={};
    this.attributes={};this.value="";this.textContent="";this.hidden=false;
    this.disabled=false;this.checked=false;this.className="";
    elements.push(this);
  }
  append(...items){this.children.push(...items);}
  prepend(...items){this.children.unshift(...items);}
  setAttribute(name,val){this.attributes[name]=val;}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  dispatchEvent(ev){for(const fn of this.listeners[ev.type]||[])fn(ev);}
  click(){this.dispatchEvent({type:"click",preventDefault(){},stopPropagation(){}});}
  removeAttribute(name){delete this.attributes[name];}
  remove(){this.removed=true;}
  showModal(){this.open=true;}
  close(){this.open=false;this.dispatchEvent({type:"close"});}
}
const storage=new Map();
const body=new FakeElement("body");
const ctx=vm.createContext({
  document:{createElement:tag=>new FakeElement(tag),body,activeElement:null},
  window:{confirm:()=>true,open:(url)=>{ctx.opened=url;}},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(k,v)=>storage.set(k,v)},
  URLSearchParams,Event:class {constructor(type){this.type=type;}},
  console,JSON,Object,String,Array,Number,Math,Date,Set,
});
vm.runInContext(source,ctx);
const {createSavePanel,hideSaverWidgets,SAVE_WIDGET_NAMES}=ctx.testApi;
const values={
  filename_prefix:"image_gen_2k",filename_template:"%prefix%_%counter%",
  source_name:"",output_directory:"generation",stage:"generation",
  tracking_id:"",counter_padding:4,counter_start:0,collision_policy:"append_revision",
  include_current_workflow_in_history:false,seed:123,
  negative_prompt:"",model_name:"Krea2",settings_json:'{"steps":8}',
};
const widgets=Object.entries(values).map(([name,value])=>
  ({name,value,serialize:true,callback(){this.invoked=true;},element:new FakeElement("textarea")}));
const node={
  widgets,inputs:[],size:[440,950],
  setSize(next){this.size=next;},setDirtyCanvas(){this.dirtied=true;},
};
const find=(n,name)=>n.widgets.find(x=>x.name===name);
const tokens=[["Filename prefix","%prefix%"],["Counter","%counter%"]];
const api={apiURL:path=>"/proxy"+path};
const panel=createSavePanel(node,{
  find,templatePreview:()=>values.filename_prefix+"_0000.png",
  issues:()=>[],repair:()=>{},tokens,api,
});
assert.equal(panel.open,false,"Settings should default collapsed");
assert.equal(panel.config.style.display,"none");
assert.ok(node.size[1]<650,"Collapsed node should shrink enough to leave an image");
assert.equal(panel.body.children.length,4,"Toolbar, settings, preview and status");
assert.equal(panel.body.children[2].style.height,"340px");
assert.equal(panel.body.children[0].children[0].textContent,"▸ Settings");
assert.equal(panel.controls.negative_prompt.value,"");
assert.equal(panel.controls.settings_json.value,'{"steps":8}');
assert.ok(SAVE_WIDGET_NAMES.includes("filename_template"));

hideSaverWidgets(node,find,true);
for(const w of widgets) {
  assert.equal(w.hidden,true,"Native widgets should be visually hidden");
  assert.notEqual(w.serialize,false,"Native widgets must still serialize");
}
panel.body.children[0].children[0].click();
assert.equal(panel.open,true);
assert.equal(panel.config.style.display,"block");
assert.ok(node.size[1]>700,"Open settings should expand node");
const prefix=panel.controls.filename_prefix;
prefix.value="new_prefix";
prefix.dispatchEvent({type:"input"});
assert.equal(find(node,"filename_prefix").value,"new_prefix",
  "Reactive editor must update existing widget, not a shadow value");

node.inputs=[{name:"source_name",link:19}];panel.refresh();
assert.equal(panel.controls.source_name.disabled,true,
  "Connected values must not be overwritten from a duplicate editor");

panel.previews=[
  {filename:"image_gen_2k_0000.png",subfolder:"generation",type:"output",
    preview_available:true,display_path:"/comfy/output/generation/image_gen_2k_0000.png"},
  {filename:"external.png",type:"",subfolder:"",preview_available:false,
    display_path:"/external/custom/external.png"}
];
panel.index=0;panel.showPreview();
assert.match(panel.img.src,/\/proxy\/view\?/);
assert.ok(panel.img.src.includes("subfolder=generation"));
panel.img.onload();
assert.equal(panel.img.style.display,"block");
panel.index=1;panel.showPreview();
assert.equal(panel.img.style.display,"none");
assert.match(panel.hint.textContent,/outside ComfyUI/);
assert.match(panel.path.textContent,/external\/custom/);
assert.equal(panel.img.attributes.src,undefined);

panel.body.children[0].children[1].click();
assert.equal(body.children.length,1,"Gear should open a preferences dialog");
const dialog=body.children[0];
assert.equal(dialog.open,true);
const slider=dialog.children.find(e=>e.tag==="input"&&e.type==="range");
assert.ok(slider);
slider.value="460";slider.dispatchEvent({type:"input"});
assert.equal(panel.preferences.previewHeight,460);
assert.equal(panel.body.children[2].style.height,"460px");
assert.ok(storage.has("mr.image_utils.saver_ui.v1"));
dialog.close();
assert.equal(dialog.removed,true);
console.log("Compact saver controls, collapse, image preview, gear and widget preservation passed");
