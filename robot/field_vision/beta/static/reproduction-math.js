(function(root){
 'use strict';
 const identity=()=>[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
 function multiply(a,b){return a.map((r,i)=>b[0].map((_,j)=>r.reduce((s,x,k)=>s+x*b[k][j],0)));}
 function turn(axis,angle){const length=Math.hypot(...axis),[x,y,z]=axis.map(v=>v/length),c=Math.cos(angle),s=Math.sin(angle),v=1-c;return [[x*x*v+c,x*y*v-z*s,x*z*v+y*s,0],[y*x*v+z*s,y*y*v+c,y*z*v-x*s,0],[z*x*v-y*s,z*y*v+x*s,z*z*v+c,0],[0,0,0,1]];}
 function forward(config,raw){
  if(raw.length!==5||raw.some(v=>!Number.isFinite(v)))throw Error('관절 값 오류');
  if(Math.abs(raw[4]-config.reference_raw_ticks[4])>5)throw Error('5번 회전이 기준에서 달라졌습니다. 별도 정합 전에는 재현하지 않습니다.');
  const q=raw.map((v,i)=>config.reference_model_radians[i]+(v-config.reference_raw_ticks[i])*config.directions[i]*2*Math.PI/4096);
  if(q.some((v,i)=>v<config.joint_limits_radians[i][0]||v>config.joint_limits_radians[i][1]))throw Error('임시 환산 각도가 모델 범위 밖입니다. 이 자세에서는 정합이 유효하지 않습니다.');
  const offset=config.model_base_offset_mm;let t=identity();const points=[offset.map(v=>-v)];
  config.chain.forEach((joint,i)=>{t=multiply(t,joint.origin);points.push([0,1,2].map(k=>t[k][3]-offset[k]));if(i<5)t=multiply(t,turn(joint.axis,q[i]));});
  return {joint_radians:q,points_mm:points,position_mm:points[points.length-1]};
 }
 const api={forward};root.SoarmReproduction=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
