(()=>{'use strict';
 const el=id=>document.getElementById(id),query=new URLSearchParams(location.search);
 const names={BSVM:'密云鸡尾酒吧',BSVS:'顺义鸡尾酒吧',BSVT:'通州高空鸡尾酒吧',BSVF:'密云富民街精酿酒馆'};
 let selectedStore=query.get('store_id')||'',invite=query.get('invite')||'',profile=null,appConfig=null,selectedTags=[];
 const setVisible=(id,on)=>el(id).classList.toggle('hidden',!on);
 const notice=(message,kind='')=>{el('status').textContent=message;el('status').className='live-message '+kind;};
 const cookie=name=>document.cookie.split('; ').find(v=>v.startsWith(name+'='))?.slice(name.length+1)||'';
 const busy=(button,on)=>{button.disabled=on;button.setAttribute('aria-busy',String(on));};
 async function request(path,method='GET',data){
  const opt={method,credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}};
  if(method!=='GET'){opt.headers['Content-Type']='application/json';opt.headers['X-Growth-CSRF']=cookie('bsv_growth_csrf');opt.body=JSON.stringify(data||{});}
  let r;try{r=await fetch('/api/v1/growth'+path,opt)}catch{throw Error('网络暂不可用，请检查连接后重试。')}
  let result={};try{result=await r.json()}catch{}
  if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'操作暂未完成，请稍后重试。');return result;
 }
 function sourceText(){return names[selectedStore]||'文森特 · 北京';}
 function chooseStore(){
  selectedStore=el('store-choice').value||'';
  el('source-label').textContent=sourceText();
 }
 function hydrateConfig(conf){
  appConfig=conf;
  for(const anchor of ['menu-link','footer-menu-link']){
   const url=String(conf.menu_url||'/cocktail/');
   try{const parsed=new URL(url,location.origin);
     if(parsed.origin===location.origin||(parsed.protocol==='https:'&&(parsed.hostname==='bsvm.cn'||parsed.hostname.endsWith('.bsvm.cn'))))el(anchor).href=parsed.href;
   }catch{}
  }
  const list=el('store-choice');list.replaceChildren();
  list.add(new Option('请选择门店',''));
  for(const store of conf.stores||[]){list.add(new Option(names[store]||store,store));}
  if(!conf.stores.includes(selectedStore))selectedStore='';
  list.value=selectedStore;
  setVisible('store-picker',!selectedStore);
  el('source-label').textContent=sourceText();
  el('wechat').disabled=!conf.enabled||!conf.wechat_enabled;
  el('wxhint').textContent=!conf.enabled?'会员服务暂不可用，请稍后再试。':
     conf.wechat_enabled?'仅用于确认会员身份，不会读取聊天记录或通讯录。':
     '当前未开放在线身份验证。请向门店工作人员咨询。';
 }
 const updateTags=()=>{document.querySelectorAll('.taste-option').forEach(btn=>btn.setAttribute('aria-pressed',String(selectedTags.includes(btn.dataset.tag))))};
 const benefitLabels={RETURN_DISCOUNT:'返场优惠',COMPANION_GIFT:'同行赠饮'};
 function paintBenefits(items){
  const target=el('benefits');target.replaceChildren();
  if(!items?.length){const row=document.createElement('div');row.className='benefits-empty';row.textContent='目前没有待使用的返场礼遇。欢迎下次再来坐坐。';target.append(row);return;}
  for(const b of items){const row=document.createElement('div');row.className='benefit';
    const left=document.createElement('div');const title=document.createElement('div');title.className='benefit-name';title.textContent=benefitLabels[b.kind]||'专属礼遇';
    const sub=document.createElement('div');sub.className='benefit-caption';sub.textContent=b.expires_at?'有效期至 '+b.expires_at.slice(0,10):'以实际核销规则为准';
    const right=document.createElement('span');right.className='benefit-badge';right.textContent='待使用';left.append(title,sub);row.append(left,right);target.append(row);}
 }
 async function paintClaims(){
  let data;try{data=await request('/public/claim-requests')}catch{return;}
  const host=el('claims');host.replaceChildren();setVisible('requests',data.requests?.length>0);
  for(const c of data.requests||[]){
    const row=document.createElement('div');row.className='claim-item';const text=document.createElement('p');
    text.textContent='邀请员工编号尾号 '+c.employee_hint+' · 这位员工是否曾向你介绍文森特？';
    const actions=document.createElement('div');actions.className='claim-actions';
    for(const [answer,label] of [[true,'是，确认邀请'],[false,'不是，拒绝认领']]){
     const btn=document.createElement('button');btn.type='button';btn.textContent=label;
     btn.addEventListener('click',async()=>{busy(btn,true);try{await request('/public/claims/'+encodeURIComponent(c.claim_id)+'/confirm','POST',{confirmed:answer});notice('已记录你的选择。','ok');await refresh()}catch(e){notice(e.message,'error')}finally{busy(btn,false)}});actions.append(btn);
    }row.append(text,actions);host.append(row);
  }
 }
 async function refresh(){
  if(!appConfig)hydrateConfig(await request('/public/config'));
  let me;try{me=await request('/public/me')}catch(e){setVisible('login',true);setVisible('register',false);setVisible('member',false);setVisible('taste',false);setVisible('privacy-control',false);setVisible('requests',false);if(e.message&&!/身份验证/.test(e.message))notice(e.message,'error');return;}
  setVisible('login',false);
  if(!me.registered){setVisible('register',true);setVisible('member',false);setVisible('taste',false);setVisible('privacy-control',false);setVisible('requests',false);el('source').textContent='注册来源：'+(names[me.source_store_id]||'已记录');return;}
  profile=me;setVisible('register',false);setVisible('member',true);setVisible('taste',true);setVisible('privacy-control',true);
  el('display-name').textContent=me.display_name&&me.display_name!=='会员'?me.display_name+'，欢迎回来':'欢迎回来';
  el('customerid').textContent='BSV · '+me.customer_id.slice(0,8).toUpperCase();
  el('tier').textContent=me.membership_status==='ACTIVE'?'有效会员':'已注册';
  el('expiry').textContent=me.membership_expires_at?me.membership_expires_at.slice(0,10):'首笔消费后激活';
  el('marketing-status').textContent=me.marketing_opt_in?'已开启活动消息':'未订阅活动消息';
  el('optout').hidden=!me.marketing_opt_in;
  paintBenefits(me.benefits);
  selectedTags=(me.taste?.tags||[]).slice(0,2);el('share-taste').checked=!!me.taste?.share_for_service;updateTags();
  await paintClaims();
 }
 el('store-choice').addEventListener('change',chooseStore);
 el('wechat').addEventListener('click',()=>{
  if(!selectedStore){notice('请先选择了解文森特的门店。','error');el('store-choice').focus();return;}
  const args=new URLSearchParams({store_id:selectedStore});if(invite)args.set('invite',invite);
  location.assign('/api/v1/growth/auth/wechat/start?'+args);
 });
 el('submit').addEventListener('click',async()=>{
  if(!el('privacy').checked){notice('请先阅读并确认会员个人信息处理说明。','error');return;}
  const btn=el('submit');busy(btn,true);
  try{await request('/public/register','POST',{display_name:el('nickname').value.trim()||'会员',privacy_accepted:true,marketing_opt_in:el('marketing').checked});notice('会员已开通，欢迎加入文森特。','ok');await refresh();}
  catch(e){notice(e.message,'error')}finally{busy(btn,false)}
 });
 document.querySelectorAll('.taste-option').forEach(btn=>btn.addEventListener('click',()=>{
  const tag=btn.dataset.tag;
  if(selectedTags.includes(tag))selectedTags=selectedTags.filter(t=>t!==tag);
  else if(selectedTags.length>=2){notice('最多选择两种风味；如需更换，请先取消一种。','error');return;}
  else selectedTags.push(tag);updateTags();
 }));
 el('save-taste').addEventListener('click',async()=>{const btn=el('save-taste');busy(btn,true);
  try{await request('/public/taste','POST',{tags:selectedTags,share_for_service:el('share-taste').checked});notice('风味偏好已保存，你可以随时修改。','ok');}
  catch(e){notice(e.message,'error')}finally{busy(btn,false)}
 });
 el('optout').addEventListener('click',async()=>{try{await request('/public/marketing-preference','POST',{marketing_opt_in:false});notice('已关闭活动消息。','ok');await refresh()}catch(e){notice(e.message,'error')}});
 el('delete').addEventListener('click',async()=>{if(!confirm('确认提交会员注销申请？公司将按相关规则核验并处理你的信息。'))return;
  try{await request('/public/delete-request','POST',{});notice('申请已收到，请通过门店工作人员查询处理进度。','ok');await refresh()}catch(e){notice(e.message,'error')}
 });
 refresh().catch(e=>notice(e.message,'error'));
})();
