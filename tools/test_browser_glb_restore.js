/* No extra packages: Node 18+ smoke test for offline GLB restore engine. */
const fs=require('fs');
const assert=require('assert');
const api=require('./restore_features_in_browser.js');
const original=fs.readFileSync('models/head-input.glb');
const v12=api.parse(original,'smoke-v12');
const modified=Buffer.from(original);
const face=v12.json.nodes.map((node,index)=>({node,index})).filter(x=>
  x.node.mesh!==undefined && /face/i.test(x.node.name||'') &&
  !/brow|lash|eye|neck|tearline/i.test(x.node.name||''))
  .sort((a,b)=>{
    const count=k=>v12.json.accessors[v12.json.meshes[k.node.mesh].primitives[0].attributes.POSITION].count;
    return count(b)-count(a);
  })[0];
assert(face,'A face node must exist in the test model');
const prim=v12.json.meshes[face.node.mesh].primitives[0];
const acc=v12.json.accessors[prim.attributes.POSITION];
assert.strictEqual(acc.componentType,5126,'POSITION must be float32');
const bv=v12.json.bufferViews[acc.bufferView];
const dv=new DataView(modified.buffer,modified.byteOffset,modified.byteLength);
const jsonLen=dv.getUint32(12,true);
const offset=12+8+jsonLen+8+(bv.byteOffset||0)+(acc.byteOffset||0);
const first=dv.getFloat32(offset,true), altered=first+0.00012;
dv.setFloat32(offset,altered,true);
// Simulate the user's v13 defect: remove brow/lash/eye object bindings and
// corrupt iris material references in the SOURCE (v13). The output must still
// contain all ORIGINAL v12 eye/brow/lash meshes, materials and textures.
const damagedDoc=api.parse(modified,'damaged-v13').json;
for (const n of damagedDoc.nodes) {
  if (/brow|lash|eye/i.test(n.name||'')) delete n.mesh;
}
for (const mat of damagedDoc.materials||[]) {
  if (/eye|iris|brown/i.test(mat.name||'')) mat.name='PURPOSEFULLY_CORRUPTED';
}
function rebuild(doc, raw) {
  const enc=new TextEncoder();
  const bytes=Buffer.from(raw);
  const rawJson=enc.encode(JSON.stringify(doc));
  const pad=(4-rawJson.length%4)%4;
  const src=new DataView(bytes.buffer,bytes.byteOffset,bytes.length);
  const oldJSONLength=src.getUint32(12,true);
  const binStart=12+8+oldJSONLength;
  const binSize=src.getUint32(binStart,true);
  const binData=bytes.subarray(binStart+8,binStart+8+binSize);
  const binPad=(4-binData.length%4)%4;
  const total=12+8+rawJson.length+pad+8+binData.length+binPad;
  const out=Buffer.alloc(total);
  out.writeUInt32LE(0x46546c67,0);
  out.writeUInt32LE(2,4);
  out.writeUInt32LE(total,8);
  out.writeUInt32LE(rawJson.length+pad,12);
  out.writeUInt32LE(0x4e4f534a,16);
  out.set(rawJson,20);
  out.fill(32,20+rawJson.length,20+rawJson.length+pad);
  const p=20+rawJson.length+pad;
  out.writeUInt32LE(binData.length+binPad,p);
  out.writeUInt32LE(0x004e4942,p+4);
  out.set(binData,p+8);
  return out;
}
const deliberatelyBrokenV13=rebuild(damagedDoc,modified);
const {bytes,report}=api.repair(original,deliberatelyBrokenV13);
assert.strictEqual(report.status,'PASS');
assert(report.retainedV12Materials>0);
assert(report.retainedV12Images>0);
const output=api.parse(bytes,'smoke-output');
const faceOut=output.json.nodes.find(n=>(n.name||'')===face.node.name);
assert(faceOut);
const outAcc=output.json.accessors[output.json.meshes[faceOut.mesh].primitives[0].attributes.POSITION];
const outBv=output.json.bufferViews[outAcc.bufferView];
const resultOffset=(outBv.byteOffset||0)+(outAcc.byteOffset||0);
const outputDV=new DataView(output.binary.buffer, output.binary.byteOffset,output.binary.byteLength);
const faceValue=outputDV.getFloat32(resultOffset,true);
assert(Math.abs(faceValue-altered)<1e-6, 'v13 geometry must take priority');
const f=(doc,re)=>doc.nodes.filter(n=>re.test(n.name||'')).map(n=>doc.meshes[n.mesh]);
for(const re of [/brow/i,/lash/i,/eye/i]) {
  const from=f(v12.json,re), result=f(output.json,re);
  assert.deepStrictEqual(result,from,'v12 facial feature meshes must stay intact');
}
assert.deepStrictEqual(output.json.materials,v12.json.materials);
assert.deepStrictEqual(output.json.images,v12.json.images);
fs.mkdirSync('offline-test-output',{recursive:true});
fs.writeFileSync('offline-test-output/test_v14.glb',bytes);
fs.writeFileSync('offline-test-output/test_report.json',JSON.stringify(report,null,2));
console.log('BROWSER_GLB_REPAIR_SMOKE_OK',JSON.stringify(report));

const html=fs.readFileSync('restore-glb-offline.html','utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
assert.strictEqual(scripts.length,2,'Offline HTML must embed both engine and interaction code');
const sourceModule=fs.readFileSync('tools/restore_features_in_browser.js','utf8').trim();
assert.strictEqual(scripts[0].trim(),sourceModule,
  'Offline HTML must contain the tested, current version of the GLB repair engine');
new Function(scripts[1]);
console.log('STANDALONE_HTML_SCRIPT_VERIFIED');
