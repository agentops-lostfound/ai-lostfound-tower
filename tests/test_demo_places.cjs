const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function setup(){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,textContent:'',children:[],append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});return nodes.get(id);};get('placeMachine').value='KIOSK-A';let readFails=false,writeGate=null;
 const requests=[],context=vm.createContext({$:get,snapshot:{revision:'a'.repeat(32)},busy:false,fresh:true,encodeURIComponent,
  el:(tag,text)=>({tag,textContent:text,children:[],append(...v){this.children.push(...v);}}),failed(){},load:async()=>{},
  render:()=>context.CollectionPlaces?.sync(context.snapshot,context.busy,context.fresh),
  api:async(url,body)=>{requests.push({url,body});if(body){if(writeGate)await writeGate;readFails=true;return {created:true,page_offset:5};}if(readFails)throw Error('목록 연결 실패');const offset=Number(new URL(url,'http://localhost').searchParams.get('offset'));return {mode:'demo_sqlite',revision:'a'.repeat(32),line:'2호선',station:'해운대',total:6,next_offset:offset===0?5:null,places:Array.from({length:offset===0?5:1},(_,i)=>({label:'가상 장소 '+(offset+i+1),line:'2호선',station:'해운대'}))};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/collection-desk/assets/places.js'),'utf8'),context);await tick();return {get,context,requests,defer:()=>{let release;writeGate=new Promise(resolve=>{release=resolve;});return release;}};
}
test('initial catalog loads five and next page shows the final entry',async()=>{
 const s=await setup();assert.equal(s.get('placeList').children.length,5);assert.equal(s.get('placeNext').disabled,false);
 s.get('placeNext').onclick();await tick();assert.equal(s.get('placeList').children.length,1);assert.equal(s.get('placeNext').disabled,true);assert.equal(s.get('placePrev').disabled,false);
});
test('place save acknowledgement is preserved when list refresh fails',async()=>{
 const s=await setup();s.get('placeLabel').value='가상 새 장소';await s.get('placeForm').onsubmit({preventDefault(){}});
 assert.match(s.get('placeStatus').textContent,/저장은 완료/);assert.equal(s.get('placeSave').disabled,true);assert.equal(s.get('placeReload').disabled,false);
 assert.equal(s.requests.find(r=>r.body).body.station,'해운대');
});
test('new text entered during an in-flight save is not erased by the previous acknowledgement',async()=>{
 const s=await setup();s.get('placeLabel').value='첫 장소';const release=s.defer(),pending=s.get('placeForm').onsubmit({preventDefault(){}});
 assert.equal(s.get('placeLabel').disabled,true);s.get('placeLabel').value='다음 장소';release();await pending;assert.equal(s.get('placeLabel').value,'다음 장소');
});
test('unsaved place labels remain associated with their selected machine',async()=>{
 const s=await setup();s.get('placeLabel').value='A용 장소';s.get('placeMachine').value='KIOSK-C';s.get('placeMachine').onchange();await tick();assert.equal(s.get('placeLabel').value,'');
 s.get('placeLabel').value='C용 장소';s.get('placeMachine').value='KIOSK-A';s.get('placeMachine').onchange();await tick();assert.equal(s.get('placeLabel').value,'A용 장소');
});
test('reset clears drafts even when the previous place list fetch failed',async()=>{
 const s=await setup();s.get('placeLabel').value='저장할 장소';await s.get('placeForm').onsubmit({preventDefault(){}});
 s.get('placeLabel').value='이전 시연 초안';s.context.snapshot={revision:'b'.repeat(32)};s.context.CollectionPlaces.sync(s.context.snapshot,true,true);
 assert.equal(s.get('placeLabel').value,'');
});
