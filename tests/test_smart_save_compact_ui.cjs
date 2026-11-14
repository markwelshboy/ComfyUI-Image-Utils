"use strict";
/* Lightweight DOM regression for the compact ComfyUI saver frontend.
 * No jsdom or GPU required: verifies the node-facing contract and reactive UI.
 */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"..","web","mr_smart_save_compact.js"),"utf8");
class Element {
 constructor(tag){
  this.tag=tag;this.children=[];this.style={};this.listeners={};this.attributes={};
  this.hidden=false;this.disabled=false;this.textContent="";this.value="";
  this.type=tag;this.checked=false;this.className="";this.parent=null;this.src="";
 }
 append(...nodes){
  for(const node of nodes){node.parent=this;this.children.push(node);}
 }
 appendChild(node){this.append(node);return node;}
 prepend(node){node.parent=this;this.children.unshift(node);}
 setAttribute(k,v){this.attributes[k]=String(v);}
 addEventListener(n,cb){(this.listeners[n]||=[]).push(cb);}
 dispatchEvent(event){
  for(const cb of this.listeners[event.type]||[]){
   cb({preventDefault(){},stopPropagation(){},...event});
  }
 }
 remove(){
  if(this.parent)this.parent.children=this.parent.children.filter(e=>e!==this);
 }
 showModal(){this.open=true;}
 close(){this.open=false;this.dispatchEvent({type:"close"});}
 click(){this.dispatchEvent({type:"click"});}
}
class MockEvent{
 constructor(type,options={}){this.type=type;this.bubbles=options.bubbles;}
}
const document={
 createElement:tag=>new Element(tag),activeElement:null,body:new Element("body")
};
const context=vm.createContext({console,document,Event:MockEvent,Date,Math,
 window:{confirm:()=>true}});
const script=source
 .replace("export const UI_SETTINGS_KEY =","const UI_SETTINGS_KEY =")
 .replace("export function buildSaverUI","function buildSaverUI")+
 "\nglobalThis.__buildSaverUI=buildSaverUI;";
vm.runInContext(script,context);
const build=context.__buildSaverUI;
assert.equal(typeof build,"function");

const original={
 filename_prefix:"image_gen_2k",include_current_workflow_in_history:true,
 source_name:"",filename_template:"%prefix%_%counter%",output_directory:"trial2k",
 stage:"generation",tracking_id:"",counter_padding:4,counter_start:0,
 collision_policy:"append_revision",seed:-1,negative_prompt:"",
 model_name:"Krea2",settings_json:"{}"
};
const widgets=Object.entries(original).map(([name,value])=>({
 name,value,type:typeof value==="boolean"?"toggle":"text",serialize:true,
 computeSize(){return [180,24]},callback(){this.callbackCount=(this.callbackCount||0)+1;},
 element:{style:{}},
}));
const node={
 widgets,size:[380,1000],properties:{},inputs:[],setDirtyCanvas(){this.dirty=true;},
 setSize(value){this.size=value;},addDOMWidget(name,type,root,options){
  const w={name,type,element:root,options,serialize:true,value:undefined};
  this.widgets.push(w);return w;
 }
};
const field=(n,name)=>n.widgets.find(w=>w.name===name);
const options={
 field,fieldNames:Object.keys(original),
 tokens:[["Filename prefix","%prefix%"],["Output counter","%counter%"]],
 estimateText:n=>"trial2k/"+field(n,"filename_prefix").value+"_0000.png",
 issues:n=>(field(n,"counter_padding").value<1?["counter_padding"]:[]),
 repair:n=>{field(n,"counter_padding").value=4;n.__mrSmartSaveNeedsReview=false;
  n.__mrSmartSaveReviewNote="Repaired";},
};
const api={apiURL:p=>"/base/proxy"+p};
const ui=build(node,api,options);
assert.ok(ui.root);
assert.ok(node.dirty);
assert.ok(node.size[0]>=440);
const wrapper=ui.root;
assert.equal(wrapper.className,"mr-saver");
const toolbar=wrapper.children[1],settings=wrapper.children[2];
const frame=wrapper.children[3],nav=wrapper.children[4],last=wrapper.children[5];
const warning=wrapper.children[6],repair=wrapper.children[7];
assert.equal(settings.hidden,true,"Settings must be collapsed by default");
assert.equal(frame.style.height,"340px");
assert.equal(node.widgets.at(-1).serialize,false);
assert.equal(node.widgets.at(-1).name,"mr_filename_preview");
for(const name of Object.keys(original)){
 const w=field(node,name);
 assert.equal(w.serialize,true,"Original widgets remain serializable: "+name);
 assert.equal(w.type,"hidden","Underlying widget presentation must be hidden: "+name);
 assert.equal(w.element.style.display,"none","Raw widget must not occupy visible space");
}
assert.equal(last.textContent,"Last save: not run yet");
assert.equal(frame.children[0].hidden,true);
assert.equal(frame.children[1].hidden,false);

toolbar.children[0].click();
assert.equal(settings.hidden,false,"Settings expand on click");
assert.ok(node.size[1]>500);
function allDescendants(node){return [node,...node.children.flatMap(allDescendants)];}
function input(name){
 const found=allDescendants(settings).find(x=>x.attributes["aria-label"]===name);
 assert.ok(found,"Missing field: "+name);return found;
}
const template=input("Filename template");
assert.equal(template.value,"%prefix%_%counter%");
template.value="%prefix%_custom_%counter%";
template.dispatchEvent({type:"input"});
assert.equal(field(node,"filename_template").value,template.value);
assert.ok(field(node,"filename_template").callbackCount>=1);
const tokens=allDescendants(settings).filter(x=>x.tag==="button"&&x.textContent==="+Filename prefix");
assert.equal(tokens.length,1);
tokens[0].click();
assert.equal(field(node,"filename_template").value,"%prefix%_custom_%counter%%prefix%");

const snapshot=Object.fromEntries(Object.keys(original).map(n=>[n,field(node,n).value]));
assert.equal(snapshot.counter_padding,4);
assert.equal(snapshot.filename_prefix,"image_gen_2k");
assert.equal(field(node,"filename_prefix").serialize,true);
node.inputs=[{name:"filename_template",link:103}];
ui.refresh();
assert.equal(template.disabled,true,"Connected input must lock editable field");
const before=field(node,"filename_template").value;
template.value="new-but-connected";
template.dispatchEvent({type:"input"});
assert.equal(field(node,"filename_template").value,before);
node.inputs=[];ui.refresh();

ui.updatePreview({
 mr_saved_preview:[{filename:"image_gen_2k_0000.png",subfolder:"trial2k",
  type:"output",available:true,display_path:"/workspace/output/trial2k/image_gen_2k_0000.png"}],
 mr_saved_paths:["/workspace/output/trial2k/image_gen_2k_0000.png"],
});
assert.equal(frame.children[0].hidden,false);
assert.ok(frame.children[0].src.includes("/base/proxy/view?filename=image_gen_2k_0000.png"),"Preview URL must use Comfy's apiURL");
assert.match(last.textContent,/image_gen_2k_0000\.png/);
frame.children[0].click();
assert.equal(document.body.children.at(-1).open,true,"Image opens full-screen dialog");
document.body.children.at(-1).close();
assert.equal(document.body.children.length,0,"Dialog cleans itself up");

ui.updatePreview({
 mr_saved_preview:[{filename:"outside.png",display_path:"/elsewhere/outside.png",available:false}],
 mr_saved_paths:["/elsewhere/outside.png"],
});
assert.equal(frame.children[0].hidden,true);
assert.match(frame.children[1].textContent,/Preview unavailable/);
ui.updatePreview({
 mr_saved_preview:[
  {filename:"a.png",subfolder:"",type:"output",available:true},
  {filename:"b.png",subfolder:"",type:"output",available:true},
 ],
 mr_saved_paths:["/out/a.png","/out/b.png"],
});
assert.equal(nav.hidden,false);
assert.match(frame.children[0].src,/b\.png/);
nav.children[0].click();assert.match(frame.children[0].src,/a\.png/);

toolbar.children[1].click();
const preferences=document.body.children.at(-1);
assert.equal(preferences.open,true);
const range=allDescendants(preferences).find(x=>x.type==="range");
range.value="490";range.dispatchEvent({type:"input"});
assert.equal(node.properties.mr_saver_ui.previewHeight,490);
assert.equal(frame.style.height,"490px");
preferences.close();assert.equal(document.body.children.length,0);
node.properties.mr_saver_ui={settingsOpen:false,previewHeight:260};
ui.applyStoredPrefs();
assert.equal(frame.style.height,"260px");
assert.equal(settings.hidden,true);
field(node,"counter_padding").value=0;
ui.refresh();
assert.equal(warning.hidden,false);
assert.match(warning.textContent,/counter_padding/);
assert.equal(repair.hidden,false);
repair.click();
assert.equal(field(node,"counter_padding").value,4);
assert.equal(repair.hidden,true);
console.log("Compact saver UI: collapse, preview, batch, metadata, reactive fields and preferences passed");
