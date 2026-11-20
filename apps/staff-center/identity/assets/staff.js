"use strict";
const {$,request,send,node,lines,safe,action,label,statusText}=BSV;
let currentTr=null;
let registrationKey;
function renderHistoryEvent(ev){
 const list=node('div','身份记录已更新','item');
 list.append(node('p',new Date(ev.occurred_at).toLocaleString('zh-CN'),'meta'));
 const detail=node('details','');
 detail.append(node('summary','查看事件编号'),node('p',ev.event_type,'mono'));
 list.append(detail);
 return list;
}
async function refresh(){
 const me=await request('/api/v1/identity/me');
 currentTr=me.tr_code;
 $('#auth-area').classList.add('hidden');
 $('#member-area').classList.remove('hidden');
 $('#tr-view').textContent=me.tr_code||'尚未领取';
 $('#register-panel').classList.toggle('hidden',!!me.tr_code);
 $('#registration-state').textContent=statusText(me.registration_status);
 const empActive=!!(me.emp_code&&me.active_legal_entities?.length&&me.active);
 const bmActive=!!(me.bm_code&&me.bm_active_entities?.length&&me.active);
 $('#stage-view').replaceChildren(
   node('p','员工身份：'+(empActive?'已生效':me.emp_code?'当前未生效':'尚未发放')),
   node('p','管理身份：'+(bmActive?'已生效':me.bm_code?'当前未生效':'尚未发放')));
 $('#code-details').textContent='人员：'+(me.tr_code||'未领取')+' · 员工：'+(me.emp_code||'未发放')+' · 管理：'+(me.bm_code||'未发放')+'。三个编号跟随同一人。';
 lines($('#grants-view'),me.grants,g=>{
   const d=node('div',label(g.action,'已授权的工作'),'item');
   d.append(node('p','岗位：'+label(g.role,'已授权岗位')+' · 范围：'+(g.store_id||label(g.legal_entity_id,'所属公司')),'meta'));
   return d;
 });
 lines($('#qual-view'),me.qualifications,q=>node('div',label(q.code,'已核实工作资格'),'item'));
}
async function signIn(endpoint,user,pass){
 const form=user.closest('form');
 await send(endpoint,{username:user.value,password:pass.value});
 pass.value='';
 registrationKey=undefined;
 try{await refresh();}
 catch{return '账号操作已确认。资料暂未加载，请刷新个人中心。';}
 $('#notice').textContent='已登录。请查看下方的入职进度与权限。';
 $('#notice').classList.remove('hidden','error');
 $('#notice').focus();
 return form.id==='signup-form'?'演练账号已创建。请查看入职申请。':'已登录。';
}
action($('#login-form'),'正在登录…',()=>signIn('/api/v1/auth/isolated/login',$('#login-user'),$('#login-pass')));
action($('#signup-form'),'正在创建账号…',()=>signIn('/api/v1/auth/isolated/signup',$('#signup-user'),$('#signup-pass')));
action($('#register-form'),'正在提交入职核验…',async()=>{
 if(!$('#consent').checked)throw new Error('请先勾选登记和审核说明。');
 registrationKey=registrationKey||crypto.randomUUID();
 const result=await send('/api/v1/identity/registrations',{legal_entity_id:$('#reg-entity').value,idempotency_key:registrationKey,display_label:$('#display-label').value,proof_hint:$('#proof-hint').value||null,consent_version:'2026-11-18'});
 try{await refresh();}catch{ /* The request returned a confirmed record even when its follow-up read is unavailable. */ }
 return '申请已保存，编号 '+result.registration_id+'。请等待两位审核同事处理。';
});
action($('#logout'),'正在退出…',async()=>{
 await send('/api/v1/auth/logout',{});
 $('#member-area').classList.add('hidden');
 $('#auth-area').classList.remove('hidden');
 $('#notice').textContent='已退出。';
 $('#notice').classList.remove('hidden','error');
 $('#login-user').focus();
 registrationKey=undefined;
 return '已退出。';
});
action($('#history'),'正在查看最近变更…',async()=>{
 if(!currentTr)throw new Error('请先完成入职核验，领取人员编号后再查看。');
 const history=await request('/api/v1/identity/'+encodeURIComponent(currentTr)+'/history');
 lines($('#history-view'),history.events,renderHistoryEvent);
 return history.events.length?'已载入最近变更。':'暂无变更记录。';
});
safe(async()=>{
 const conf=await request('/api/v1/identity/public-config');
 for(const entity of conf.registration_entities){
   const option=node('option',label(entity,entity));
   option.value=entity;
   $('#reg-entity').append(option);
 }
 try{await refresh();}catch(error){if(error.status!==401)throw error;}
});
