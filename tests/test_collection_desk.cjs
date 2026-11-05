const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
class Element{
 constructor(){this.children=[];this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.classList={toggle(){}};}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=[...children];}
 setAttribute(){}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function setup(){
 const nodes=new Map(),requests=[],board={mode:'demo_sqlite',revision:'a'.repeat(32),event_count:0,items:[
  {item_id:'A-W01',machine_id:'KIOSK-A',category:'지갑',color:'검정',status:'등록기계 보관'},
  {item_id:'A-W02',machine_id:'KIOSK-A',category:'USB',color:'회색',status:'등록기계 보관'}],collections:[],alerts:[]};
 const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};get('machine').value='KIOSK-A';
 let fail=false,failRead=false,failAfterWrite=false;
 const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},crypto:require('node:crypto').webcrypto,AbortSignal,Intl,console,
  fetch:async(url,options)=>{const body=options.body?JSON.parse(options.body):null;requests.push({url,body,headers:options.headers});if(fail&&url==='/collections'||failRead&&url==='/collection-dashboard')throw Error('connection interrupted');if(failAfterWrite&&url==='/collections')failRead=true;return {ok:true,json:async()=>url==='/collection-dashboard'?structuredClone(board):{collection_id:1,missing_item_ids:['A-W02']}};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/collection-desk/assets/desk.js'),'utf8'),context);await tick();
 return {nodes,get,requests,board,context,setFail:value=>{fail=value;},setFailRead:value=>{failRead=value;},setFailAfterWrite:value=>{failAfterWrite=value;}};
}
test('failed pickup retries with identical request key and frozen selection',async()=>{
 const s=await setup();s.get('selectAll').onclick();s.setFail(true);await s.get('pickup').onclick();
 assert.equal(s.get('retryPickup').hidden,false);assert.equal(s.get('machine').disabled,true);
 s.setFail(false);await s.get('retryPickup').onclick();
 const calls=s.requests.filter(r=>r.url==='/collections');assert.equal(calls.length,2);assert.deepEqual(calls[0].body,calls[1].body);assert.equal(s.get('retryPickup').hidden,true);
});
test('zero-arrival submission needs a second explicit action',async()=>{
 const s=await setup();s.board.collections=[{collection_id:1,machine_id:'KIOSK-A',picked_at:'2026-11-05T00:00:00Z',arrived_at:null,items:[{item_id:'A-W01',category:'지갑',color:'검정',arrived:false}]}];await s.get('refresh').onclick();
 const button=()=>s.get('batchList').children[0].children.at(-1).children.at(-1);
 button().onclick();assert.equal(s.requests.filter(r=>r.url.includes('/arrivals')).length,0);assert.match(button().textContent,/0개 도착/);
 await button().onclick();await tick();assert.deepEqual(s.requests.find(r=>r.url.includes('/arrivals')).body,{item_ids:[]});
});
test('arrival drafts survive refresh and completed items stay locked',async()=>{
 const s=await setup();s.board.collections=[{collection_id:1,machine_id:'KIOSK-A',picked_at:'2026-11-05T00:00:00Z',arrived_at:null,items:[{item_id:'A-W01',category:'지갑',color:'검정',arrived:true},{item_id:'A-W02',category:'USB',color:'회색',arrived:false}]}];await s.get('refresh').onclick();
 const rows=()=>s.get('batchList').children[0].children[2].children;
 assert.equal(rows()[0].children[0].disabled,true);const input=rows()[1].children[0];input.checked=true;input.onchange();
 await s.get('refresh').onclick();assert.equal(rows()[1].children[0].checked,true);
});
test('acknowledged save and failed refresh are distinguished and block stale mutation',async()=>{
 const s=await setup();s.get('selectAll').onclick();s.setFailAfterWrite(true);await s.get('pickup').onclick();
 assert.match(s.get('message').textContent,/저장은 완료/);assert.match(s.get('message').textContent,/목록/);
 assert.equal(s.get('pickup').disabled,true);assert.equal(s.get('reset').disabled,true);
 const count=s.requests.filter(r=>r.url==='/collections').length;await s.get('pickup').onclick();assert.equal(s.requests.filter(r=>r.url==='/collections').length,count);
 s.setFailRead(false);await s.get('refresh').onclick();assert.equal(s.get('reset').disabled,false);
});
test('a reset in another window clears old selections and sends current revision',async()=>{
 const s=await setup();s.get('selectAll').onclick();s.board.revision='b'.repeat(32);await s.get('refresh').onclick();
 assert.equal(s.get('pickup').disabled,true);s.get('selectAll').onclick();await s.get('pickup').onclick();
 assert.equal(s.requests.find(r=>r.url==='/collections').headers['x-demo-revision'],'b'.repeat(32));
});
test('failed refresh keeps arrival controls locked until fresh data is loaded',async()=>{
 const s=await setup();s.board.collections=[{collection_id:1,machine_id:'KIOSK-A',picked_at:'2026-11-05T00:00:00Z',arrived_at:null,items:[{item_id:'A-W01',category:'지갑',color:'검정',arrived:false}]}];await s.get('refresh').onclick();
 s.setFailRead(true);await s.get('refresh').onclick();const card=s.get('batchList').children[0];assert.equal(card.children[2].children[0].children[0].disabled,true);assert.equal(card.children.at(-1).children.at(-1).disabled,true);
});
