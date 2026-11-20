"use strict";
(() => {
 const {$,request}=BSV;
 function card(id,state,label,description){
   const tag=$('#'+id+'-status');
   tag.dataset.state=state;
   tag.textContent=label;
   $('#'+id+'-next').textContent=description;
 }
 async function supply(me){
   const actions=new Set((me?.grants||[]).map(grant=>grant.action));
   const mayInspect=[...actions].some(action=>action.startsWith('quality.'));
   try{
     const health=await request('/supply-ui/api/health');
     if(health.mode!=='internal-stage')throw new Error('Unexpected service mode');
     card('supply','blocked','暂未启用','中央台账尚未连接。可查看授权范围，配送、收货与盘点都不能提交。');
     card('inspection','read','仅查看',
          mayInspect?'可核对已授权门店。督查记录和复核尚不能提交。'
                    :'可查看开放情况。需要督查权限时，请向总部申请对应门店。');
   }catch{
     card('supply','blocked','状态待确认','暂时无法获取供货状态。请检查连接，再刷新本页。');
     card('inspection','blocked','状态待确认','暂时无法获取督查状态。请检查连接，再刷新本页。');
   }
 }
 async function load(){
   let me;
   try{
     me=await request('/api/v1/identity/me');
   }catch(error){
     const signedOut=error.status===401;
     $('#session-summary').textContent=signedOut?'尚未登录':'暂时无法确认登录状态';
     $('#session-link').textContent=signedOut?'登录或申请入职':'前往个人中心';
     card('employee','read',signedOut?'可登录':'请检查连接','进入个人中心后查看入职进度和可用权限。');
     card('pos','blocked','待核验','先登录，再核对可点单门店和员工 PIN。');
     card('hq','blocked','待核验','请用已获总部授权的账号登录。');
     await supply();
     return;
   }
   const grants=me.grants||[];
   const stores=[...new Set(grants.map(grant=>grant.store_id).filter(Boolean))];
   const orderStores=stores.filter(store=>['pos.order.read','pos.order.create'].every(action=>
      grants.some(grant=>grant.store_id===store&&grant.action===action)));
   const hq=grants.some(grant=>grant.action==='hq.people.read');
   const roles=[];
   if(me.emp_code&&me.active_legal_entities?.length)roles.push('员工');
   if(grants.some(grant=>grant.role==='manager'))roles.push('当班负责人');
   if(hq)roles.push('总部');
   if(grants.some(grant=>grant.action.startsWith('quality.independent.')))roles.push('独立督查');
   $('#session-summary').textContent=me.tr_code?'已登录 · '+(roles.join(' / ')||'可查看个人资料'):'已登录 · 入职待核验';
   $('#store-summary').textContent=stores.length?'可核对的门店：'+stores.join('、'):'当前没有门店授权';
   card('employee','ready','可操作',me.tr_code?'查看人员编号、已生效的任职和个人资格。':'在个人中心提交申请，或查看审核进度。');
   card('pos',orderStores.length?'ready':'blocked',orderStores.length?'可进行门店核验':'暂未授权',
        orderStores.length?'已获点单权限：'+orderStores.join('、')+'。进入点单台核对员工码和 PIN。'
                          :'如果今天需要点单，请向总部申请当班门店权限。');
   card('hq',hq?'ready':'blocked',hq?'可操作':'暂未授权',
        hq?'按已授权的所属公司查询人员和处理待审事项。':'切换到拥有总部权限的账号后继续。');
   await supply(me);
 }
 load();
})();
