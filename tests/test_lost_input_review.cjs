const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
 const nodes=new Map(),events=new Map(),requests=[],replies=[];
 const get=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',disabled:false,hidden:true,textContent:'',className:'',files:[],listeners:{},addEventListener(n,f){this.listeners[n]=f;},scrollIntoView(){},focus(){}});return nodes.get(id);};
 get('mode').value='text';get('text').value='검정 휴대폰';get('lost_date').value='2026-11-10';get('lost_line').value='1호선';get('lost_station').value='초량역';
 const context=vm.createContext({document:{getElementById:get,dispatchEvent(){},addEventListener(n,f){events.set(n,f);}},Event:class{},window:{addEventListener(){}},navigator:{},AbortController,Blob,TypeError,Error,Map,setTimeout,clearTimeout,requestAnimationFrame:f=>f(),
 FileReader:class{readAsDataURL(file){this.result=file.url||'data:'+file.type+';base64,YQ==';this.onload();}},
 fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});const reply=replies.shift();if(reply instanceof Error)throw reply;return reply?await reply:{ok:true,json:async()=>url.endsWith('/confirm')?{description:{category:'모형폰',color:'검정'},lost_date:'2026-11-10',lost_line:'1호선',lost_station:'초량역'}:{proposal_id:'synthetic-proposal',description:{category:'모형폰',color:'검정'},warnings:[]}};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/lost-input/assets/input.js'),'utf8'),context);
 return {get,context,requests,replies,submit:()=>get('entry').onsubmit({preventDefault(){}}),edit:(id,value)=>{get(id).value=value;get(['category','color','shape','mark','material','visible_text'].includes(id)?'review':'entry').listeners.input({target:get(id)});},defer(){let release;replies.push(new Promise(r=>release=r));return release;},proposal:()=>vm.runInContext('proposal',context),confirmed:()=>vm.runInContext('confirmedSearchContext',context)};
}
const result=()=>({ok:true,json:async()=>({proposal_id:'old',description:{category:'립밤',color:'분홍'},warnings:[]})});
test('review edits are sent and clearing metadata does not restore a previous value',async()=>{
 const s=setup();await s.submit();s.edit('color','파랑');s.edit('lost_station','');await s.get('confirm').onclick();
 assert.equal(s.requests[1].body.description.color,'파랑');assert.equal(s.requests[1].body.lost_station,'');
});
test('editing source invalidates old review and prevents confirming it',async()=>{
 const s=setup();await s.submit();s.edit('text','흰색 립밤');await s.get('confirm').onclick();
 assert.equal(s.proposal(),null);assert.equal(s.get('review').hidden,true);assert.equal(s.requests.length,1);
});
test('source changed while preparing discards a late response without erasing the new text',async()=>{
 const s=setup(),release=s.defer(),pending=s.submit();s.edit('text','새 설명');release(result());await pending;
 assert.equal(s.proposal(),null);assert.equal(s.get('review').hidden,true);assert.equal(s.get('text').value,'새 설명');assert.equal(s.get('prepare').disabled,false);
});
test('mode changes discard pending results and clear a file selected for another mode',async()=>{
 const s=setup(),release=s.defer(),pending=s.submit();s.get('mode').value='photo';s.get('file').value='old.wav';s.get('mode').onchange();release(result());await pending;
 assert.equal(s.get('file').value,'');assert.equal(s.proposal(),null);assert.equal(s.confirmed(),null);
});
test('double prepare and confirmation clicks issue one request each',async()=>{
 const s=setup(),release=s.defer(),pending=s.submit();await s.submit();assert.equal(s.requests.length,1);release(result());await pending;
 const confirmRelease=s.defer(),confirm=s.get('confirm').onclick();await s.get('confirm').onclick();assert.equal(s.requests.length,2);confirmRelease({ok:true,json:async()=>({description:{category:'립밤'}})});await confirm;
});
test('editing while confirmation is pending cannot restore an obsolete search context',async()=>{
 const s=setup();await s.submit();const release=s.defer(),pending=s.get('confirm').onclick();s.edit('color','파랑');release({ok:true,json:async()=>({description:{category:'모형폰',color:'검정'}})});await pending;
 assert.equal(s.confirmed(),null);assert.equal(s.get('searchReviewed').hidden,true);assert.match(s.get('notice').textContent,/입력이 바뀌었/);
});
test('metadata changes discard in-flight extraction results',async()=>{
 const s=setup(),release=s.defer(),pending=s.submit();s.edit('lost_station','부산역');release(result());await pending;
 assert.equal(s.proposal(),null);assert.equal(s.get('lost_station').value,'부산역');
});
test('successful confirmation is invalidated by changing or clearing a review field',async()=>{
 const s=setup();await s.submit();await s.get('confirm').onclick();assert.ok(s.confirmed());s.edit('mark','별 스티커');assert.equal(s.confirmed(),null);assert.equal(s.get('searchReviewed').hidden,true);
});
test('server validation failure preserves original inputs and permits retry',async()=>{
 const s=setup();s.replies.push({ok:false,json:async()=>({detail:'음성을 인식하지 못했습니다'})});await s.submit();
 assert.equal(s.get('text').value,'검정 휴대폰');assert.equal(s.proposal(),null);assert.equal(s.get('prepare').disabled,false);await s.submit();assert.ok(s.proposal());
});
for(const [name,reply,pattern] of [['HTML response',{ok:false,json:async()=>{throw SyntaxError();}},/서버 응답/],['network error',new TypeError('Failed to fetch'),/서버에 연결/],['timeout',Object.assign(new Error(),{name:'AbortError'}),/오래 걸리고/]]){
 test(name+' preserves the input and shows a useful recovery message',async()=>{const s=setup();s.replies.push(reply);await s.submit();assert.match(s.get('notice').textContent,pattern);assert.equal(s.get('text').value,'검정 휴대폰');assert.equal(s.get('prepare').disabled,false);});
}
test('invalid or empty media is rejected without posting and is not replaced by old text results',async()=>{
 for(const file of [{type:'text/plain',size:100},{type:'image/png',size:0},{type:'image/png',size:6*1024*1024}]){
  const s=setup();s.get('mode').value='photo';s.get('mode').onchange();s.get('file').files=[file];await s.submit();assert.equal(s.requests.length,0);assert.equal(s.proposal(),null);assert.equal(s.get('prepare').disabled,false);
 }
});
test('file replacement clears a previously recorded audio selection',async()=>{
 const s=setup();vm.runInContext('recordedWav=new Blob(["old"],{type:"audio/wav"})',s.context);s.get('file').listeners.change();assert.equal(vm.runInContext('recordedWav',s.context),null);
});
test('permission response arriving after mode change releases microphone tracks',async()=>{
 const s=setup();let release,stops=0;s.context.navigator.mediaDevices={getUserMedia:()=>new Promise(r=>release=r)};s.get('mode').value='audio';s.get('mode').onchange();const pending=s.get('record').onclick();s.get('mode').value='text';s.get('mode').onchange();release({getTracks:()=>[{stop(){stops++;}}]});await pending;assert.equal(stops,1);assert.equal(vm.runInContext('recorder',s.context),null);
});
