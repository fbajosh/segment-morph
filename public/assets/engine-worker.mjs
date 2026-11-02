// Browser-only geometry worker. Uploads remain inside this browser process.
// Pyodide and its packages are downloaded from a pinned public CDN; no project
// data is sent to Cloudflare, Pyodide, or other third parties.
const runtimeURL = 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full/pyodide.mjs';
const runtimeIndex = 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full/';
const modules = ['__init__.py','geometry.py','graph.py','motion.py','unfold.py','hypermorph.py','sequence.py','sequence_export.py'];
let ready;
async function initialize(){
  const {loadPyodide} = await import(runtimeURL);
  const pyodide = await loadPyodide({indexURL:runtimeIndex});
  await pyodide.loadPackage(['networkx']);
  pyodide.FS.mkdirTree('/home/pyodide/segment_morph');
  await Promise.all(modules.map(async filename => {
    const url = new URL(`../py/segment_morph/${filename}`, import.meta.url);
    const response = await fetch(url);
    if(!response.ok)throw Error(`Unable to load geometry module: ${filename}`);
    pyodide.FS.writeFile(`/home/pyodide/segment_morph/${filename}`, await response.text());
  }));
  pyodide.runPython(`import json\nfrom segment_morph.sequence import create_sequence_project\nfrom segment_morph.sequence_export import export_sequence_svg`);
  postMessage({type:'ready'});
  return pyodide;
}
ready=initialize();
self.onmessage=async ({data})=>{
 const {id,action,payload}=data;
 try {
   const pyodide=await ready;
   pyodide.globals.set('sm_payload',JSON.stringify(payload));
   let result;
   if(action==='generate'){
     const raw=pyodide.runPython(`_sm=json.loads(sm_payload)\njson.dumps(create_sequence_project(_sm['images'], order=_sm['order'], durations=_sm['durations'], holds=_sm['holds'], motion=_sm['motion'], mode=_sm['mode'], tolerance=_sm['tolerance'], frames_per_leg=_sm['frames_per_leg']))`);
     result=JSON.parse(raw);
   } else if(action==='export-svg'){
     result=pyodide.runPython(`_sm=json.loads(sm_payload)\nexport_sequence_svg(_sm['project'],fps=_sm['fps'])`);
   } else throw Error('Unknown action');
   postMessage({id,result});
 } catch(error){postMessage({id,error:String(error?.message||error)});}
};
