// Segment Morph Studio v0.9 — browser-local processing, visual overrides, schema migration.
const $=id=>document.getElementById(id);
const ns='http://www.w3.org/2000/svg';
const clamp=(n,a=0,b=1)=>Math.min(b,Math.max(a,n));
const lerp=(a,b,t)=>a+(b-a)*t;
const labels={A:'Image A',B:'Image B',C:'Image C'};
const initialNames={A:'No file selected',B:'No file selected',C:'No file selected'};
const DEFAULT_EXPORT_FPS=60;
const DEFAULT_APPEARANCE={color_override:null,width_override:null};
const worker=new Worker(new URL('./engine-worker.mjs',import.meta.url),{type:'module'});
const requests=new Map();let sequenceId=0, engineReady=false, engineError=null;
worker.addEventListener('message',({data})=>{
  if(data.type==='ready') {engineReady=true; $('stageStatus').textContent='Local engine ready · upload A, B, and C';return;}
  const request=requests.get(data.id);if(!request)return;requests.delete(data.id);
  if(data.error)request.reject(Error(data.error));else request.resolve(data.result);
});
worker.addEventListener('error',event=>{
  engineError=event.message||'Local Python runtime could not load';
  for(const request of requests.values())request.reject(Error(engineError));requests.clear();
  $('stageStatus').textContent=engineError;
});
function localTask(action,payload){return new Promise((resolve,reject)=>{if(engineError){reject(Error(engineError));return;}const id=++sequenceId;requests.set(id,{resolve,reject});worker.postMessage({id,action,payload});});}
function appearance(){return p?.export||DEFAULT_APPEARANCE;}
function displayStroke(leg,u){return appearance().color_override||color(leg.stroke_from,leg.stroke_to,u);}
function displayWidth(leg,u){return appearance().width_override??lerp(leg.width_from,leg.width_to,u);}
function updateAppearance(){
  if(!p)return;
  const rawWidth=Number($('strokeWidth').value);
  if($('overrideWidth').checked&&(!Number.isFinite(rawWidth)||rawWidth<=0||rawWidth>100)){
    notify('Stroke width must be between 0.1 and 100',true);return;
  }
  p.export.color_override=$('overrideColor').checked?$('strokeColor').value:null;
  p.export.width_override=$('overrideWidth').checked?rawWidth:null;
  draw();
}

const defaultMotion={easing:'linear',rotation_step_deg:55,depth_strength:.72,stagger:.72,hinge_release:.45,return_twist_deg:34};
let p=null,images={A:null,B:null,C:null},names={...initialNames},progress=0,playing=false,frameHandle=null,lastTick=null,busy=false;
function notify(message,error=false){const el=$('toast');el.textContent=message;el.style.background=error?'#983f55':'#202739';el.classList.remove('hidden');clearTimeout(notify.id);notify.id=setTimeout(()=>el.classList.add('hidden'),4300);}
function parseOrder(value){const raw=value.trim().toUpperCase();const names=/^[ABC]+$/.test(raw)&&raw.length>1?raw.split(''):raw.split(/(?:\s+|→|->|,|;|\|)+/).filter(Boolean);if(names.length<2||names.length>12)throw Error('Use 2–12 sequence entries, e.g. A → B → A → C');if(names.some(c=>!['A','B','C'].includes(c)))throw Error('Sequence can only contain A, B or C');return names;}
function renderOrderPreview(){const node=$('sequencePreview');node.replaceChildren();try{const order=parseOrder($('order').value);$('orderError').textContent='';const sequence=[...order,order[0]];sequence.forEach((key,i)=>{if(i){const arrow=document.createElement('span');arrow.className='sequence-arrow';arrow.textContent='→';node.append(arrow);}const span=document.createElement('span');span.className='sequence-chip'+(i===order.length?' closing':'');span.textContent=key+(i===order.length?' ↻':'');node.append(span);});return order;}catch(error){$('orderError').textContent=error.message;return null;}}
function legDuration(leg){return Number(leg.duration)+Number(leg.hold||0);}
function totalDuration(){return p?p.legs.reduce((sum,l)=>sum+legDuration(l),0):0;}
function locate(t){
 const total=totalDuration();let sec=clamp(t)*total;
 for(let i=0;i<p.legs.length;i++){
   const leg=p.legs[i],move=Number(leg.duration),hold=Number(leg.hold||0),length=move+hold;
   if(sec<length||i===p.legs.length-1){
     const frozen=sec>=move;
     return {index:i,local:frozen?1:clamp(sec/move),holding:frozen,time:clamp(t)*total};
   }
   sec-=length;
 }
 return {index:0,local:0,holding:false,time:0};
}
function sample(leg,u){const frames=leg.frames;const x=clamp(u)*(frames.length-1),i=Math.min(frames.length-2,Math.floor(x)),frac=x-i;const start=frames[i],end=frames[i+1];return start.map((v,k)=>v.map((n,j)=>lerp(n,end[k][j],frac)));}
function frame(at=progress){if(!p)return null;const atLeg=locate(at),leg=p.legs[atLeg.index];return {...atLeg,leg,lines:sample(leg,atLeg.local)};}
function edgeNode(a,b,c,d,stroke,width){const el=document.createElementNS(ns,'line');for(const [key,v] of Object.entries({x1:a,y1:b,x2:c,y2:d,stroke,'stroke-width':width,'stroke-linecap':'round','vector-effect':'non-scaling-stroke'}))el.setAttribute(key,String(v));return el;}
function mini(letter){const svg=$('mini'+letter);if(!p)return;const graph=p.graphs[letter],idmap=Object.fromEntries(graph.vertices.map(v=>[v.id,v]));const lines=graph.edges.map(e=>{const a=idmap[e.source],b=idmap[e.target];return edgeNode(a.x,a.y,b.x,b.y,p?.export?.color_override||e.stroke,p?.export?.width_override??2.2);});svg.replaceChildren(...lines);svg.setAttribute('viewBox',`0 0 ${p.viewport.width} ${p.viewport.height}`);}
function color(a,b,u){if(a===b)return a;const valid=s=>/^#[0-9a-f]{6}$/i.test(s);if(!valid(a)||!valid(b))return u<.5?a:b;return '#'+[1,3,5].map(i=>Math.round(lerp(parseInt(a.slice(i,i+2),16),parseInt(b.slice(i,i+2),16),u)).toString(16).padStart(2,'0')).join('');}
function draw(){if(!p)return;const f=frame(),nodes=f.lines.map(v=>edgeNode(...v,displayStroke(f.leg,f.local),displayWidth(f.leg,f.local)));
$('stage').replaceChildren(...nodes);$('stage').setAttribute('viewBox',`0 0 ${p.viewport.width} ${p.viewport.height}`);
$('timeline').value=Math.round(progress*1000);$('progressLabel').textContent=(progress*100).toFixed(1)+'%';$('timeLabel').textContent=(f.time).toFixed(2)+' s';
$('stageStatus').textContent=f.holding?`Holding ${f.leg.to} · ${Number(f.leg.hold||0).toFixed(2)} s`:`${f.leg.from} → ${f.leg.to} · ${f.leg.kind}${f.leg.hinges?` · ${f.leg.hinges} hinges`:''}`;
$('segmentCount').textContent=f.lines.length+' line segments';document.querySelectorAll('[data-step]').forEach(btn=>btn.classList.toggle('active',Number(btn.dataset.step)===f.index));}
function renderPhases(){if(!p)return;const row=$('phaseRow');row.replaceChildren();let elapsed=0;const total=totalDuration();const seq=[...p.order,p.order[0]];seq.forEach((state,i)=>{const btn=document.createElement('button');btn.className='phase-button';btn.textContent=`${state}${i===p.order.length?' ↻':''}`;btn.dataset.step=String(Math.min(i,p.order.length-1));btn.title=`Jump to ${state}`;const point=elapsed/total;btn.onclick=()=>{pause();progress=point;draw();};row.append(btn);if(i<p.legs.length)elapsed+=legDuration(p.legs[i]);});$('canvasTitle').textContent=seq.join(' → ');}
function renderDurations(){
 const container=$('durationRows');container.replaceChildren();
 p.legs.forEach((leg,index)=>{
   const block=document.createElement('div');block.className='duration-row';
   const title=document.createElement('div');title.className='duration-title';title.textContent=`${index+1}. ${leg.from} → ${leg.to}`;block.append(title);
   function addSlider(text,value,min,max,onUpdate){
     const line=document.createElement('div');line.className='range-label';
     const label=document.createElement('label');label.textContent=text;
     const output=document.createElement('output');output.textContent=Number(value).toFixed(2)+' s';
     line.append(label,output);
     const input=document.createElement('input');input.type='range';input.min=min;input.max=max;input.step='.05';input.value=value;
     input.addEventListener('input',()=>{
       const v=Number(input.value);onUpdate(v);output.textContent=v.toFixed(2)+' s';renderPhases();draw();
     });block.append(line,input);
   }
   addSlider('Move',leg.duration,.25,15,v=>{leg.duration=v;p.durations[index]=v;});
   addSlider(`Freeze on ${leg.to}`,leg.hold||0,0,15,v=>{leg.hold=v;p.holds[index]=v;});
   container.append(block);
 });
}
function syncMotion(){for(const [id,key,mult,suffix] of [['rotation','rotation_step_deg',1,'°'],['depth','depth_strength',100,'%'],['stagger','stagger',100,'%'],['hinge','hinge_release',100,'%'],['twist','return_twist_deg',1,'°']]){const value=p.motion[key];$(id).value=value;$(id+'Value').textContent=Math.round(value*mult)+suffix;}$('easing').value=p.motion.easing;}
function sync(){for(const letter of ['A','B','C']){$('name'+letter).textContent=names[letter];mini(letter);}let stats=Object.entries(p.graphs).map(([k,g])=>`${k}: ${g.vertices.length} vertices, ${g.edges.length} edges`).join(' · ');$('graphStats').textContent=stats;
$('planStats').textContent=p.legs.map(leg=>`${leg.from}→${leg.to}: ${leg.kind}${leg.hinges?' / '+leg.hinges+' hinges':''}`).join(' · ');
$('order').value=p.order.join(' → ');renderOrderPreview();$('exportFps').value=String(p.export.fps);
$('overrideColor').checked=!!p.export.color_override;
$('strokeColor').value=p.export.color_override||'#000000';
$('overrideWidth').checked=p.export.width_override!=null;
$('strokeWidth').value=String(p.export.width_override??2);
$('strategy').value=p.planning.mode;$('tolerance').value=p.planning.tolerance;$('toleranceValue').textContent=Number(p.planning.tolerance).toFixed(2);
$('duration').value=p.durations[0];$('durationValue').textContent=Number(p.durations[0]).toFixed(1)+' s';$('defaultHold').value=p.holds[0];$('defaultHoldValue').textContent=Number(p.holds[0]).toFixed(2)+' s';syncMotion();renderPhases();renderDurations();draw();}
function load(next){
 if(next.engine!=='three-svg-sequence'||![6,7,8,9].includes(next.schema_version)||!Array.isArray(next.legs))throw Error('Expected a Segment Morph Studio v0.6–v0.9 project');
 pause();p=next;
 // Migrate old files without frozen intervals; existing v0.6 animation timing is preserved.
 p.holds=Array.isArray(p.holds)&&p.holds.length===p.legs.length?p.holds.map(Number):p.legs.map(leg=>Number(leg.hold||0));
 p.legs.forEach((leg,i)=>leg.hold=p.holds[i]);
 const savedFps=Number(p.export?.fps);p.export={...(p.export||{}),fps:Number.isInteger(savedFps)&&savedFps>=12&&savedFps<=120?savedFps:DEFAULT_EXPORT_FPS};
 const ec=p.export.color_override,ew=Number(p.export.width_override);
 p.export.color_override=typeof ec==='string'&&/^#[0-9a-fA-F]{6}$/.test(ec)?ec:null;
 p.export.width_override=p.export.width_override!=null&&Number.isFinite(ew)&&ew>0&&ew<=100?ew:null;
 p.schema_version=9;
 images={...p.images};progress=0;sync();
}
// No HTTP requests with project data. Both actions execute in a Web Worker in this browser.
async function api(endpoint,data){
 if(endpoint==='/api/sequence/project')return localTask('generate',data);
 throw Error('Unknown local operation');
}
function motionFromUI(){return {easing:$('easing').value,rotation_step_deg:Number($('rotation').value),depth_strength:Number($('depth').value),stagger:Number($('stagger').value),hinge_release:Number($('hinge').value),return_twist_deg:Number($('twist').value)};}
async function rebuild(useCurrentMotion=false){const order=renderOrderPreview();if(!order)return;for(const k of ['A','B','C'])if(!images[k]){notify(`Upload image ${k} as SVG`,true);return;}
if(busy)return;busy=true;pause();const button=$('process');button.disabled=true;button.textContent='Calculating…';$('stageStatus').textContent='Calculating transition geometry…';try{
 const sameOrder=p&&p.order.join()==order.join();
 const durations=order.map((_,i)=>sameOrder&&p.durations[i]!=null?p.durations[i]:Number($('duration').value));
 const holds=order.map((_,i)=>sameOrder&&p.holds[i]!=null?p.holds[i]:Number($('defaultHold').value));
 const retainedFps=p?.export?.fps??(Number($('exportFps').value)||DEFAULT_EXPORT_FPS);
 const data=await api('/api/sequence/project',{images,order,durations,holds,motion:useCurrentMotion?motionFromUI():p?.motion||defaultMotion,mode:$('strategy').value,tolerance:Number($('tolerance').value),frames_per_leg:61});
 data.export={...data.export,fps:retainedFps,color_override:p?.export?.color_override??null,width_override:p?.export?.width_override??null};load(data);notify('Loop generated');play();
}catch(e){notify(e.message,true);$('stageStatus').textContent='Unable to calculate loop';}finally{busy=false;button.disabled=false;button.textContent='Generate loop';}}
function clearProject(){
 pause();p=null;progress=0;images={A:null,B:null,C:null};names={...initialNames};
 for(const key of ['A','B','C']){
   $('name'+key).textContent=initialNames[key];$('mini'+key).replaceChildren();
   $('file'+key).value='';
 }
 $('stage').replaceChildren();$('stageStatus').textContent='Upload A, B, and C to begin · local processing';$('exportFps').value=String(DEFAULT_EXPORT_FPS);
 $('overrideColor').checked=false;$('strokeColor').value='#000000';$('overrideWidth').checked=false;$('strokeWidth').value='2';
 $('segmentCount').textContent='—';$('graphStats').textContent='';$('planStats').textContent='';
 $('phaseRow').replaceChildren();$('durationRows').replaceChildren();
 $('timeline').value='0';$('progressLabel').textContent='0%';$('timeLabel').textContent='0.0 s';
 $('canvasTitle').textContent='A → B → A → C → A';
 renderOrderPreview();notify('Project cleared');
}
function pause(){playing=false;lastTick=null;if(frameHandle)cancelAnimationFrame(frameHandle);frameHandle=null;$('play').textContent='▶';}
function tick(now){if(!playing||!p)return;if(lastTick!==null){progress=(progress+(now-lastTick)/1000*Number($('speed').value)/totalDuration())%1;draw();}lastTick=now;frameHandle=requestAnimationFrame(tick);}
function play(){if(!p)return;if(playing){pause();return;}playing=true;lastTick=null;$('play').textContent='Ⅱ';frameHandle=requestAnimationFrame(tick);}
function save(name,content,mime){const blob=new Blob([content],{type:mime});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1500);}
function downloadFrame(){if(!p)return;const f=frame();const content=f.lines.map(v=>`<line x1="${v[0]}" y1="${v[1]}" x2="${v[2]}" y2="${v[3]}"/>`).join('');const svg=`<svg xmlns="${ns}" viewBox="0 0 ${p.viewport.width} ${p.viewport.height}" fill="none" stroke="${displayStroke(f.leg,f.local)}" stroke-width="${displayWidth(f.leg,f.local)}">${content}</svg>`;save('segment-morph-frame.svg',svg,'image/svg+xml');}
async function exportSVG(){
 if(!p)return;
 try{
   const raw=await localTask('export-svg',{project:p,fps:p.export?.fps??DEFAULT_EXPORT_FPS});
   const xml=new DOMParser().parseFromString(raw,'image/svg+xml');
   if(xml.querySelector('parsererror'))throw Error('Invalid generated SVG');
   const path=xml.querySelector('path');if(!path)throw Error('Missing animation path');
   if(p.export?.color_override){
     path.setAttribute('stroke',p.export.color_override);
     path.querySelectorAll('animate[attributeName="stroke"]').forEach(e=>e.remove());
   }
   if(p.export?.width_override!=null){
     path.setAttribute('stroke-width',String(p.export.width_override));
     path.querySelectorAll('animate[attributeName="stroke-width"]').forEach(e=>e.remove());
   }
   save('segment-morph-loop.svg',new XMLSerializer().serializeToString(xml),'image/svg+xml');
   notify('Animated SVG exported');
 }catch(e){notify(e.message,true);}
}
function exportHTML(){if(!p)return;const data=JSON.stringify({legs:p.legs,viewport:p.viewport}).replaceAll('<','\\u003c');
 const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Segment Morph Loop</title><style>html,body{margin:0;width:100%;height:100%;display:grid;place-items:center;background:transparent}svg{display:block;width:100%;height:100%;max-width:100vw;max-height:100vh}</style><svg id="stage" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${p.viewport.width} ${p.viewport.height}"></svg><script>
const p=${data},svg=document.getElementById('stage'),ns='http://www.w3.org/2000/svg',total=p.legs.reduce((n,l)=>n+l.duration+(l.hold||0),0);let start=null;
function render(now){if(start===null)start=now;let time=((now-start)/1000)%total,index=0;while(index<p.legs.length-1&&time>p.legs[index].duration+(p.legs[index].hold||0))time-=p.legs[index].duration+(p.legs[index++].hold||0);const leg=p.legs[index],u=Math.max(0,Math.min(1,time/leg.duration)),x=u*(leg.frames.length-1),i=Math.min(leg.frames.length-2,Math.floor(x)),q=x-i,a=leg.frames[i],b=leg.frames[i+1];const nodes=a.map((v,k)=>{const n=document.createElementNS(ns,'line');for(const [key,z] of Object.entries({x1:v[0]*(1-q)+b[k][0]*q,y1:v[1]*(1-q)+b[k][1]*q,x2:v[2]*(1-q)+b[k][2]*q,y2:v[3]*(1-q)+b[k][3]*q,stroke:p.export?.color_override||(u<.5?leg.stroke_from:leg.stroke_to),'stroke-width':p.export?.width_override??(leg.width_from*(1-u)+leg.width_to*u),'stroke-linecap':'round'}))n.setAttribute(key,z);return n;});svg.replaceChildren(...nodes);requestAnimationFrame(render);}requestAnimationFrame(render);
<\/script></html>`;
 save('segment-morph-loop.html',html,'text/html');notify('Standalone HTML exported');}
function controls(){
$('clearProject').onclick=clearProject;$('process').onclick=()=>rebuild(true);$('order').addEventListener('input',renderOrderPreview);$('order').addEventListener('keydown',e=>{if(e.key==='Enter')rebuild(true);});
$('duration').oninput=()=>{const d=Number($('duration').value);$('durationValue').textContent=d.toFixed(1)+' s';if(p){p.durations=p.order.map(()=>d);for(const leg of p.legs)leg.duration=d;renderDurations();renderPhases();draw();}};
$('defaultHold').oninput=()=>{const h=Number($('defaultHold').value);$('defaultHoldValue').textContent=h.toFixed(2)+' s';if(p){p.holds=p.order.map(()=>h);for(const leg of p.legs)leg.hold=h;renderDurations();renderPhases();draw();}};$('tolerance').oninput=()=>{$('toleranceValue').textContent=Number($('tolerance').value).toFixed(2);};
for(const key of ['A','B','C'])$('file'+key).addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;if(!file.name.toLowerCase().endsWith('.svg')){notify('Upload a .svg file',true);return;}if(file.size>2_000_000){notify('An SVG must be 2 MB or smaller',true);return;}const content=await file.text();if(!/<svg(?:\s|>)/i.test(content)){notify('File does not contain an SVG element',true);return;}images[key]=content;names[key]=file.name;$('name'+key).textContent=file.name;notify(`${key} loaded: ${file.name}. Select Generate loop to apply.`);});
$('openProject').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{const loaded=JSON.parse(await file.text());names={A:'Uploaded A',B:'Uploaded B',C:'Uploaded C'};load(loaded);notify('Project loaded');}catch(err){notify(err.message,true);}});
$('downloadProject').onclick=()=>p&&save('segment-morph-sequence-v0.9.json',JSON.stringify(p,null,2),'application/json');
$('exportFps').onchange=()=>{if(p)p.export.fps=Number($('exportFps').value);};$('overrideColor').addEventListener('change',updateAppearance);
$('strokeColor').addEventListener('input',updateAppearance);
$('overrideWidth').addEventListener('change',updateAppearance);
$('strokeWidth').addEventListener('change',updateAppearance);
$('downloadSVG').onclick=exportSVG;$('downloadHTML').onclick=exportHTML;$('downloadFrame').onclick=downloadFrame;
$('play').onclick=play;$('jumpStart').onclick=()=>{pause();progress=0;draw();};$('jumpEnd').onclick=()=>{pause();progress=1;draw();};$('timeline').oninput=e=>{pause();progress=Number(e.target.value)/1000;draw();};
for(const [id,suffix,mult] of [['rotation','°',1],['depth','%',100],['stagger','%',100],['hinge','%',100],['twist','°',1]])$(id).addEventListener('input',()=>{$(id+'Value').textContent=Math.round(Number($(id).value)*mult)+suffix;});
$('applyMotion').onclick=()=>rebuild(true);$('resetMotion').onclick=()=>{if(!p)return;p.motion={...defaultMotion};syncMotion();rebuild(true);};}
window.SegmentMorphV9={getProject:()=>p,frame,parseOrder,locate};controls();renderOrderPreview();
