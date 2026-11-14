"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const js=fs.readFileSync(path.join(__dirname,"..","web","mr_smart_save.js"),"utf8");
const begin=js.indexOf("function findWidget(");
const end=js.indexOf("function addLabel(",begin);
assert.ok(begin>=0&&end>begin,"Expected frontend filename-preview helper");
const funcs=js.slice(begin,end)+"\nthis.templatePreview=templatePreview;";
const context={Date};vm.runInNewContext(funcs,context);

function node(template,prefix="image_gen_2k"){
  const opts={filename_prefix:prefix,filename_template:template,source_name:"",
    counter_padding:4,counter_start:0,seed:-1,stage:"generation",output_directory:"trial2k"};
  return {widgets:Object.entries(opts).map(([name,value])=>({name,value})),inputs:[]};
}

const actual=context.templatePreview(node("%prefix%_%counter%"));
assert.ok(actual.startsWith("trial2k/image_gen_2k_0000.png"),actual);
assert.ok(!actual.includes("filename_prefix omitted"),actual);

const unprefixed=context.templatePreview(node("%counter%"));
assert.ok(unprefixed.startsWith("trial2k/0000.png"),unprefixed);
assert.ok(unprefixed.includes("filename_prefix omitted"),unprefixed);

const legacy=context.templatePreview(node(""));
assert.equal(legacy,"Legacy filename mode: image_gen_2k_00001_.png");
assert.ok(js.includes('["Filename prefix", "%prefix%"]'),"Missing + Filename prefix button");

console.log("Smart save frontend prefix-token preview checks passed");
