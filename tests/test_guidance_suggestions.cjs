const test = require('node:test');
const assert = require('node:assert/strict');
const {rank,normalize} = require('../web/lost-input/assets/suggestions.js');
const items = [
  {id:'pickup',text:'물건 수령 방법',keywords:['수령','예약'],count:0},
  {id:'identity',text:'개인정보 저장 방법',keywords:['개인정보','저장'],count:2},
  {id:'hours',text:'운영시간 안내',keywords:['시간','주말'],count:1}
];
test('typing spaced Korean privacy keyword finds the relevant question',()=>{
  assert.equal(rank(items,'개인 정보')[0].id,'identity');
});
test('unknown question does not suggest an unrelated topic',()=>{
  assert.deepEqual(rank(items,'오늘 날씨'),[]);
});
test('empty suggestions use actual selection counts',()=>{
  assert.deepEqual(rank(items,'').map(item=>item.id),['identity','hours','pickup']);
});
test('normalization handles fullwidth characters and zero width spacing',()=>{
  assert.equal(normalize('Ａ\u200b B？'),'ab');
});
