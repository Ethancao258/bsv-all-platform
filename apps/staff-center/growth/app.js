(()=>{'use strict';
 const el=id=>document.getElementById(id),q=new URLSearchParams(location.search);
 const base='/api/v1/growth',titles={service:['CUSTOMER SERVICE','当前接待','在点单时识别会员，让推荐更加贴合当下的口味。'],claims:['CUSTOMER CLAIM','客户认领','确认真实获客贡献，认领记录清楚可追溯。'],invite:['INVITE & CONNECT','我的推广','把好的体验分享给朋友，推荐关系由系统记录。'],signature:['MY SIGNATURE','我的签名','规范保存签名母版，后续文件无需重复书写。']};
 let identity=null,policy=null,inviteLink='',hasDrawn=false,activeView='service';
 const visitContext=q.get('context')||(()=>{const match=location.hash.match(/(?:^|&)context=([^&]+)/);try{return match?decodeURIComponent(match[1]):''}catch{return ''}})();
 const selectedStore=()=>el('store').value;
 const cookie=n=>document.cookie.split('; ').find(v=>v.startsWith(n+'='))?.slice(n.length+1)||'';
 const status=(message,error=false)=>{const x=el('status');x.hidden=!message;x.textContent=message;x.classList.toggle('error',error);};
 const busy=(node,state)=>{node.disabled=state;node.setAttribute('aria-busy',String(state));};
 async function api(path,method='GET',data){
   const headers={Accept:'application/json'};
   if(method!=='GET'){headers['Content-Type']='application/json';headers['X-Growth-CSRF']=cookie('bsv_dev_csrf')||cookie('bsv_growth_csrf');headers['X-CSRF-Token']=cookie('bsv_csrf');}
   let response;try{response=await fetch(base+path,{method,headers,credentials:'same-origin',cache:'no-store',...(method!=='GET'?{body:JSON.stringify(data||{})}:{})})}catch{throw Error('网络连接中断，请稍后再试。')}
   let payload={};try{payload=await response.json()}catch{}
   if(!response.ok)throw Error(typeof payload.detail==='string'?payload.detail:'操作未完成，请刷新后重试。');return payload;
 }
 function showView(which){
   if(!titles[which])return;
   activeView=which;
   for(const name of Object.keys(titles)){
     el('view-'+name).classList.toggle('active',name===which);
     for(const btn of document.querySelectorAll('[data-view="'+name+'"]')){
       if(name===which)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current');
     }
   }
   el('section-kicker').textContent=titles[which][0];el('section-title').textContent=titles[which][1];el('section-summary').textContent=titles[which][2];
   if(location.hash.slice(1)!==which)history.replaceState(null,'',location.pathname+location.search+'#'+which);
   window.scrollTo({top:0,behavior:'instant'});
 }
 document.querySelectorAll('[data-view]').forEach(btn=>btn.addEventListener('click',()=>showView(btn.dataset.view)));
 function removeContext(){el('service-empty').hidden=false;el('service-present').hidden=true;}
 async function loadContext(){
   const ctx=visitContext;if(!ctx){removeContext();return;}
   try{
      const result=await api('/staff/guest-context?context='+encodeURIComponent(ctx));
      el('service-empty').hidden=true;el('service-present').hidden=false;
      const tags=el('service-tags');tags.replaceChildren();
      if(result.share_for_service&&result.tags?.length){for(const t of result.tags){const tag=document.createElement('span');tag.textContent=t;tags.append(tag)}}
      else{const empty=document.createElement('p');empty.textContent='客人尚未分享风味偏好。';empty.className='intro';tags.append(empty)}
      el('service-guidance').textContent=result.guidance;
   }catch(err){removeContext();status(err.message,true)}
 }
 async function loadPolicy(){
    policy=null;
    try{
       const p=await api('/staff/policy?store_id='+encodeURIComponent(selectedStore()));
       if(!p.configured){el('policy-current').textContent=p.notice||'本店认领暂未开放。';el('claim').disabled=true;return}
       policy=p;el('claim').disabled=false;
       el('policy-current').textContent='现行政策 '+p.version+' · 基准佣金率 '+(p.base_rate_bps/100).toFixed(2)+'% · 开发前'+p.full_days+'天按全额，之后'+p.reduced_days+'天按基准率的'+(p.reduced_coeff_bps/100).toFixed(0)+'%。最终按有效协议和订单核验。';
    }catch(e){el('policy-current').textContent='目前无法核对佣金规则，请稍后重试。';el('claim').disabled=true;status(e.message,true)}
 }
 async function loadQueue(){
   const data=await api('/staff/queue?store_id='+encodeURIComponent(selectedStore()));
   const host=el('queue');host.replaceChildren();el('queue-count').hidden=!data.tickets?.length;el('queue-count').textContent=data.tickets?.length||'';
   if(!data.tickets?.length){const empty=document.createElement('p');empty.className='empty-line';empty.textContent='当前没有待认领客户。新客户完成门店注册后，会显示在这里。';host.append(empty);return;}
   for(const t of data.tickets){
      const item=document.createElement('div');item.className='ticket';
      const txt=document.createElement('div');const strong=document.createElement('strong');strong.textContent='客户识别码 '+t.short_id;
      const small=document.createElement('small');small.textContent='注册于 '+new Date(t.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
      txt.append(strong,small);
      const action=document.createElement('button');action.className='button button-light';action.type='button';action.textContent='选择';
      action.addEventListener('click',()=>{el('ticket-id').value=t.ticket_id;el('ticket').value=t.short_id;el('claim-form').scrollIntoView({behavior:'smooth',block:'center'});});
      item.append(txt,action);host.append(item);
   }
 }
 async function loadIdentity(){
   identity=null;policy=null;removeContext();el('service-tags').replaceChildren();
   try{
     const data=await api('/staff/me?store_id='+encodeURIComponent(selectedStore()));
     identity=data;el('who').textContent=data.name+' · '+data.actor_tr;el('who-note').textContent='已核对当前门店访问权限';
     el('full-name').value=data.name||'';
     el('signature-status').textContent=data.signature_version?'已保存 · 第'+data.signature_version+'版':'尚未录入';
     el('signature-saved').hidden=!data.signature_version;
     if(data.signature_version)el('saved-image').src='/api/v1/growth/staff/signature-preview?store_id='+encodeURIComponent(selectedStore())+'&v='+data.signature_version;
     await Promise.all([loadQueue(),loadPolicy(),loadContext()]);
     if(!visitContext)status('');
   }catch(e){el('who').textContent='暂时无法使用客户工作台';el('who-note').textContent='请从员工中心登录，并确认本店岗位权限';el('claim').disabled=true;el('signature-saved').hidden=true;status(e.message,true);}
 }
 el('refresh').addEventListener('click',loadIdentity);
 el('store').addEventListener('change',()=>{el('ticket').value='';el('ticket-id').value='';identity=null;loadIdentity();});
 el('queue-refresh').addEventListener('click',()=>loadQueue().catch(e=>status(e.message,true)));
 el('invitation').addEventListener('click',async()=>{
   const b=el('invitation');busy(b,true);
   try{
     const response=await api('/staff/invite?store_id='+encodeURIComponent(selectedStore()),'POST');
     const params=new URLSearchParams({store_id:response.store_id,invite:response.invite});inviteLink=location.origin+'/member/?'+params;
     el('invite-link').hidden=false;el('invite-link').textContent=inviteLink;
     el('invite-qr').hidden=false;el('qr-empty').hidden=true;
     el('invite-qr').src=base+'/staff/invite-qr?store_id='+encodeURIComponent(selectedStore())+'&v='+Date.now();
     el('copy-link').hidden=false;el('open-link').hidden=false;el('open-link').href=inviteLink;
     status('邀请二维码已生成，可直接发送给朋友。');
   }catch(e){status(e.message,true)}finally{busy(b,false)}
 });
 el('copy-link').addEventListener('click',async()=>{
   try{await navigator.clipboard.writeText(inviteLink);status('邀请链接已复制。')}
   catch{status('当前设备无法自动复制，请长按下方链接。',true)}
 });
 el('claim').addEventListener('click',async()=>{
   if(!el('ticket-id').value){status('请先选择待认领客户。',true);showView('claims');return;}
   if(!policy){status('本店佣金政策尚未确认，暂不能提交认领。',true);return;}
   if(!el('attest').checked){status('请先确认本次认领声明。',true);return;}
   const btn=el('claim');busy(btn,true);
   try{
     await api('/staff/claims?store_id='+encodeURIComponent(selectedStore()),'POST',{
       ticket_id:el('ticket-id').value,attested:true,evidence_note:el('evidence').value.trim(),policy_version:policy.version});
     el('ticket-id').value='';el('ticket').value='';el('evidence').value='';el('attest').checked=false;
     status('认领申请已提交。请客户本人在会员页面确认邀请关系。');await loadQueue();
   }catch(e){status(e.message,true)}finally{busy(btn,false)}
 });
 const canvas=el('signature'),ctx=canvas.getContext('2d');ctx.strokeStyle='#2e302c';ctx.lineWidth=4;ctx.lineCap='round';ctx.lineJoin='round';let drawing=false;
 function pos(evt){const r=canvas.getBoundingClientRect();return{x:(evt.clientX-r.left)*canvas.width/r.width,y:(evt.clientY-r.top)*canvas.height/r.height}}
 canvas.addEventListener('pointerdown',evt=>{drawing=true;hasDrawn=true;canvas.setPointerCapture(evt.pointerId);let p=pos(evt);ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(p.x+.1,p.y+.1);ctx.stroke()});
 canvas.addEventListener('pointermove',evt=>{if(!drawing)return;const p=pos(evt);ctx.lineTo(p.x,p.y);ctx.stroke()});
 for(const event of ['pointerup','pointercancel'])canvas.addEventListener(event,()=>drawing=false);
 el('clear').addEventListener('click',()=>{ctx.clearRect(0,0,canvas.width,canvas.height);hasDrawn=false});
 el('save-signature').addEventListener('click',async()=>{
   if(!hasDrawn){status('请先写下完整姓名。',true);return;}
   if(!identity){status('人员身份尚未核验，无法保存签名。',true);return;}
   const b=el('save-signature');busy(b,true);
   try{
     const result=await api('/staff/signature?store_id='+encodeURIComponent(selectedStore()),'POST',{
       full_name:el('full-name').value,png_data:canvas.toDataURL('image/png')});
     el('signature-status').textContent='已保存 · 第'+result.signature_version+'版';
     el('signature-saved').hidden=false;
     el('saved-image').src=base+'/staff/signature-preview?store_id='+encodeURIComponent(selectedStore())+'&v='+result.signature_version;
     status('签名母版已更新。正式合同仍需本人逐份确认。');
     ctx.clearRect(0,0,canvas.width,canvas.height);hasDrawn=false;
   }catch(e){status(e.message,true)}finally{busy(b,false)}
 });
 const initial=visitContext?'service':(titles[location.hash.slice(1)]?location.hash.slice(1):'service');
 async function bootstrap(){
   showView(initial);
   const storeChoice=el('store');storeChoice.replaceChildren(new Option('核验门店中…',''));
   storeChoice.disabled=true;
   try{
      const grants=await api('/staff/store-options');
      const allowed=grants.stores||[];
      if(!allowed.length)throw Error('当前账号尚未取得任何门店授权。');
      storeChoice.replaceChildren();
      for(const id of allowed){storeChoice.add(new Option({BSVM:'密云鸡尾酒吧',BSVS:'顺义鸡尾酒吧',BSVT:'通州高空鸡尾酒吧',BSVF:'密云富民街精酿酒馆'}[id]||id,id));}
      const preferred=q.get('store_id');if(preferred&&allowed.includes(preferred))storeChoice.value=preferred;
      storeChoice.disabled=false;await loadIdentity();
   }catch(e){el('who').textContent='暂时无法使用客户工作台';el('who-note').textContent='请登录员工中心并检查门店授权';status(e.message,true);}
 }
 bootstrap();
})();
