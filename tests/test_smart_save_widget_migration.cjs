"use strict";
/* Simulate saver creation, load, configure, serialize and intentional repair
 * without requiring ComfyUI, a browser, or a GPU.
 */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"..","web","mr_smart_save.js"),"utf8");
let extension;
const fakeApp={registerExtension(ext){extension=ext;}};
const notifications=[];
const ctx=vm.createContext({
  __api:{apiURL:p=>p},
  __hide(node,find,hidden){for(const w of node.widgets||[])w.hidden=hidden;},
  __panel(node,{issues,repair,find}){
    const root={children:[],append(...x){this.children.push(...x);}};
    const warn={hidden:true,textContent:""};
    const reset={hidden:true,click(){
      repair(node);
      display.refresh();
    }};
    root.append({textContent:"Toolbar"},{textContent:"Image preview"},warn,reset);
    const display={
      body:root,preferences:{previewHeight:340},open:false,
      path:{textContent:""},previews:[],index:0,
      drawLayout(){this.refresh();},
      showPreview(){},
      refresh(){
        const bad=issues(node);
        warn.hidden=!bad.length && !node.__mrSmartSaveNeedsReview &&
          !node.__mrSmartSaveLegacy && !node.__mrSmartSaveReviewNote;
        warn.textContent=bad.length ? "Misaligned: "+bad.join(", ") :
          (node.__mrSmartSaveReviewNote||"");
        reset.hidden=!bad.length&&!node.__mrSmartSaveNeedsReview;
      },
    };
    return display;
  },
  __app:fakeApp,
  console:{warn(...a){notifications.push(a.join(" "));}},
  window:{confirm:()=>true},
  document:{createElement(tag){
    const obj={
      tag,children:[],style:{cssText:""},attributes:{},listeners:{},
      hidden:false,textContent:"",
      setAttribute(name,value){this.attributes[name]=value;},
      addEventListener(name,callback){this.listeners[name]=callback;},
      append(...children){this.children.push(...children);},
      click(){this.listeners.click?.({preventDefault(){},stopPropagation(){}});},
    };
    return obj;
  }},
  Date,Math,JSON,Object,Number,Array,Set,String,RegExp,
});
const script=source
  .replace('import { app } from "../../scripts/app.js";',
           "const app=globalThis.__app;")
  .replace('import { api } from "../../scripts/api.js";',
           "const api=globalThis.__api;")
  .replace('import { createSavePanel, hideSaverWidgets } from "./mr_smart_save_panel.js";',
           "const createSavePanel=globalThis.__panel; const hideSaverWidgets=globalThis.__hide;");
vm.runInContext(script,ctx);
assert.ok(extension,"Smart Save extension must register");

function widget(name,value,isTextarea=false){
  return {name,value,serialize:true,callback(){},
    element:isTextarea?ctx.document.createElement("textarea"):undefined};
}
const values={
 filename_prefix:"image_gen_2k",
 include_current_workflow_in_history:true,
 source_name:"",
 filename_template:"%prefix%_%counter%",
 output_directory:"trial2k",
 stage:"generation",
 tracking_id:"",
 counter_padding:4,
 counter_start:0,
 collision_policy:"append_revision",
 seed:-1,
 negative_prompt:"",
 model_name:"Krea2",
 settings_json:'{"steps":10}',
};
const NodeType=function(){};
extension.beforeRegisterNodeDef(NodeType,{name:"ImageUtilsSaveImageWithSidecar"});

function createNode(){
  const node=Object.create(NodeType.prototype);
  node.widgets=Object.entries(values).map(([key,val])=>
    widget(key,val,key==="negative_prompt"||key==="settings_json"));
  node.inputs=[{name:"positive_prompt",link:99}];
  node.setDirtyCanvas=()=>{};
  node.addDOMWidget=function(name,type,element,options){
    const w={name,type,element,options,serialize:true,value:undefined};
    this.widgets.push(w);
    this.previewRoot=element;
    return w;
  };
  node.onNodeCreated();
  return node;
}

const node=createNode();
assert.equal(node.widgets.at(-1).name,"mr_filename_preview");
assert.equal(node.widgets.at(-1).serialize,false,
  "Preview widget must never add positional workflow values");
assert.ok(node.widgets.find(w=>w.name==="negative_prompt").hidden,
  "Native textarea is visually hidden; custom panel draws its labeled input");
assert.ok(node.__mrSavePanel && node.__mrSavePanel.body,
  "Compact saver panel must be installed");

const firstSave={properties:{}};
node.onSerialize(firstSave);
const own=firstSave.properties.mr_smart_save_named_values;
assert.equal(own.version,1);
assert.equal(own.fields.filename_template,values.filename_template);
assert.equal(own.fields.output_directory,"trial2k");
assert.equal(own.fields.counter_padding,4);
assert.equal(own.fields.settings_json,'{"steps":10}');
assert.equal(own.needs_review,false);
assert.ok(!Object.hasOwn(own.fields,"mr_filename_preview"),
  "Helper must be omitted from named values");

// Simulate positional restore shifting or mutating several fields.
node.widgets.find(w=>w.name==="output_directory").value="generation";
node.widgets.find(w=>w.name==="stage").value="";
node.widgets.find(w=>w.name==="tracking_id").value=4;
node.widgets.find(w=>w.name==="counter_padding").value=0;
node.widgets.find(w=>w.name==="counter_start").value=NaN;
node.widgets.find(w=>w.name==="collision_policy").value=-1;
node.onConfigure({properties:firstSave.properties,widgets_values:[1,2,3]});
for(const [field,expected] of Object.entries(values)){
  assert.equal(node.widgets.find(w=>w.name===field).value,expected,
    "Named saver snapshot should restore "+field);
}
assert.ok(node.previewRoot.children.length>=4);
const warning=node.previewRoot.children.at(-2);
const repair=node.previewRoot.children.at(-1);
assert.equal(warning.hidden,true,"Correct snapshot must clear alignment warning");
assert.equal(repair.hidden,true,"No repair button when named values are valid");

// ComfyUI's newer named values work without our custom property.
node.widgets.find(w=>w.name==="counter_padding").value=0;
node.onConfigure({widgets_values_named:{counter_padding:8},widgets_values:[1,2,3]});
assert.equal(node.widgets.find(w=>w.name==="counter_padding").value,8);

const damaged=createNode();
for(const [field,value] of Object.entries({
 output_directory:"generation",stage:"",tracking_id:4,
 counter_padding:0,counter_start:NaN,collision_policy:-1,
})){
 damaged.widgets.find(w=>w.name===field).value=value;
}
damaged.onConfigure({properties:{},widgets_values:Array(14).fill(null)});
assert.equal(damaged.previewRoot.children.at(-2).hidden,false);
assert.equal(damaged.previewRoot.children.at(-1).hidden,false);
assert.match(damaged.previewRoot.children.at(-2).textContent,/counter_padding/);
assert.match(damaged.previewRoot.children.at(-2).textContent,/output_directory/);
const corrupt={properties:{}};
damaged.onSerialize(corrupt);
assert.equal(corrupt.properties.mr_smart_save_named_values.needs_review,true);
damaged.previewRoot.children.at(-1).click();
for(const [field,expected] of Object.entries({
 output_directory:"",stage:"detailer-pipe",tracking_id:"",
 counter_padding:4,counter_start:0,collision_policy:"append_revision",
 seed:-1,negative_prompt:"",model_name:"",settings_json:"{}",
})){
 assert.equal(damaged.widgets.find(w=>w.name===field).value,expected,
   "Repair should reset "+field);
}
assert.equal(damaged.widgets.find(w=>w.name==="filename_prefix").value,"image_gen_2k");
assert.equal(damaged.widgets.find(w=>w.name==="filename_template").value,
 "%prefix%_%counter%");
assert.equal(damaged.previewRoot.children.at(-1).hidden,true);
const repaired={properties:{}};
damaged.onSerialize(repaired);
assert.equal(repaired.properties.mr_smart_save_named_values.needs_review,false);

// Legacy minimal saver with just two saved widget values should not be
// incorrectly flagged as corrupted.
const old=createNode();
old.onConfigure({properties:{},widgets_values:["ImageUtils",true]});
assert.equal(old.__mrSmartSaveLegacy,false);
assert.equal(old.previewRoot.children.at(-2).hidden,true);

console.log("Smart Saver named workflow snapshot, legacy detection, and repair passed");
