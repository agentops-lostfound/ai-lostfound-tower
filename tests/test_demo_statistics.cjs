const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',hidden:true,disabled:false,value:''});return nodes.get(id);};
 const result={database_mode:'demo_sqlite',count:1,revision:'a'.repeat(32),answer:'USB 1건입니다.',filters:{day:'2026-11-05',machine_id:'KIOSK-A',category:'USB',start_inclusive:'2026-11-05T00:00:00+09:00',end_exclusive:'2026-11-06T00:00:00+09:00'},sql:'SELECT count(*) FROM demo_stats_item WHERE category=?',parameters:['USB'],source:'demo_stats_item'};
 let failure=null,gate=null;const requests=[];
 const context=vm.createContext({$:get,snapshot:{revision:result.revision},busy:false,fresh:true,Number,Date,JSON,
  timeLabel:()=> '11.5 12:00',api:async(url,body)=>{requests.push({url,body});if(gate)await gate;if(failure)throw failure;return structuredClone(result);},
  failed:()=>{},load:async()=>{},render:()=>context.CollectionStats?.sync(context.snapshot,context.busy,context.fresh)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/collection-desk/assets/statistics.js'),'utf8'),context);
 get('statsQuestion').value='오늘 등록기계 A에 들어온 USB 몇 개?';
 return {get,result,context,requests,submit:()=>get('statsForm').onsubmit({preventDefault(){}}),fail:error=>{failure=error;},defer:()=>{let release;gate=new Promise(resolve=>{release=resolve;});return release;}};
}
test('zero is a real query result and SQL is rendered as text',async()=>{
 const s=setup();s.result.count=0;s.result.sql='<script>bad()</script>';await s.submit();
 assert.equal(s.get('statsCount').textContent,'0건');assert.equal(s.get('statsResult').hidden,false);
 assert.match(s.get('statsStatus').textContent,/0건/);assert.equal(s.get('statsSql').textContent,s.result.sql);
});
test('unsupported new question hides previous result and leaves collection controls available',async()=>{
 const s=setup();await s.submit();const error=Error('지원하지 않는 조건입니다');error.status=422;s.fail(error);await s.submit();
 assert.equal(s.get('statsResult').hidden,true);assert.equal(s.context.busy,false);assert.equal(s.context.fresh,true);
 assert.equal(s.get('statsStatus').textContent,error.message);
});
test('editing question or resetting dataset invalidates displayed count',async()=>{
 const s=setup();await s.submit();s.get('statsQuestion').oninput();assert.equal(s.get('statsResult').hidden,true);
 await s.submit();s.context.CollectionStats.sync({revision:'b'.repeat(32)},false,true);
 assert.equal(s.get('statsResult').hidden,true);assert.match(s.get('statsStatus').textContent,/초기화/);
});
test('busy or stale collection state cannot start a statistics request',async()=>{
 const s=setup();s.context.fresh=false;await s.submit();assert.equal(s.requests.length,0);
 s.context.fresh=true;s.context.busy=true;await s.submit();assert.equal(s.requests.length,0);
});
test('in-flight question is locked and an edited question never receives the old answer',async()=>{
 const s=setup(),release=s.defer(),pending=s.submit();assert.equal(s.get('statsQuestion').disabled,true);
 s.get('statsQuestion').value='어제 전체 물건 접수 몇 개?';s.get('statsQuestion').oninput();release();await pending;
 assert.equal(s.get('statsResult').hidden,true);assert.match(s.get('statsStatus').textContent,/질문이 변경/);assert.equal(s.get('statsQuestion').disabled,false);
});
