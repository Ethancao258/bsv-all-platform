'use strict';

// Loaded before the existing supply app. Reuses its session, catalogue and stores.
const central = {revision:0, shipmentId:'', planId:'', printLabels:null,lastPrintByStore:new Map()};
const centralStatus = {
  DRAFT:'草稿', READY:'待发货', FOR_DISPATCH:'待发货', ALLOCATED:'已拣货', IN_TRANSIT:'在途', DISPATCHED:'在途',
  PARTIAL_RECEIVED:'部分签收', RECEIVED:'已签收', ACCEPTED:'合格', HOLD:'隔离', EXPIRED:'已过期',
  SCRAPPED:'已处置', RETURNED:'已退回', RELEASED:'已放行', PRINT:'发起打印', REPRINT:'发起重印',
  CONFIRM:'已确认实物', CONFIRMED:'已确认', SUGGESTED:'可生成计划', REVIEW_REQUIRED:'待核对', PLANNED:'已确认', DISPUTED:'有差异', CLOSED:'已结案'
};
const centralRoles = (...roles) => roles.some(role => state.me.roles.includes(role));
const centralStore = () => $('central-store').value;
const centralData = result => result?.data ?? result;
const centralEntries = (result, key) => Array.isArray(result) ? result : result?.[key] ?? [];
const zhCentral = value => centralStatus[value] || value || '';
const centralName = id => state.stores.find(x=>x.store_id===id)?.name_zh || id;
const centralList = value => String(value ?? '').split(/[\s,，]+/).filter(Boolean);
const localDateTime = value => value ? value + '+08:00' : '';
const beijingTime = value => {
  if(!value)return '—';
  const date=new Date(value);
  return Number.isNaN(date.valueOf())?'—':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date);
};
const localNow = () => new Date(Date.now()+8*60*60*1000).toISOString().slice(0,16);
const formInput = (name,label,type='text',attributes='required') =>
  `<label>${label}<input name="${name}" type="${type}" ${attributes}></label>`;
const formAmount = (name,label,value='0') => formInput(name,label,'text',
  `inputmode="decimal" pattern="[0-9]+([.][0-9]{1,4})?" value="${value}" required`);
const selectField = (name,label,options,required=true) => `<label>${label}<select name="${name}" ${required?'required':''}>${options}</select></label>`;
const selectOption = (id,label) => `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
const fieldGroup = (title,fields) => `<fieldset><legend>${title}</legend>${fields}</fieldset>`;
const submitButton = text => `<button type="submit" class="primary">${text}</button>`;
const manualIds = (name,label,required=false) =>
  `<label>${label}<textarea name="${name}" spellcheck="false" ${required?'required':''} placeholder="每行一个，或用逗号分隔"></textarea></label>`;
const centralUrl = (path,params={}) => {
  const query=new URLSearchParams();
  for(const [key,value] of Object.entries(params)){
    if(Array.isArray(value))value.forEach(item=>query.append(key,item));
    else if(value!==''&&value!=null)query.set(key,value);
  }
  return path+(query.size?'?'+query.toString():'');
};

function centralTable(headers,rows){
  if(!rows.length)return '<p class="hint">暂无记录。</p>';
  return `<div class="tablewrap"><table><thead><tr>${headers.map(x=>`<th scope="col">${x}</th>`).join('')}</tr></thead><tbody>
    ${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function enableCentral(){
  if(!state.centralCandidate||state.mode==='internal-stage')return;
  const views=[];
  if(workspace==='hq'&&centralRoles('dispatch'))views.push(['plan','补货及制作'],['labels','物料标签']);
  if(workspace!=='inspector'&&centralRoles('dispatch','receive'))views.push(['shipment','配送与签收']);
  if(workspace!=='inspector'&&centralRoles('dispatch','receive'))views.push(['inventory','库存与效期']);
  if(workspace!=='inspector'&&centralRoles('receive','dispatch'))views.push(['tasks','上下班待办']);
  if(centralRoles('dispatch','receive','inspect_independent','review_independent'))views.push(['exceptions','异常与督查']);
  if(!views.length||!state.stores.length)return;
  const store=state.stores.find(x=>x.kind!=='warehouse')||state.stores[0];
  $('central-store').innerHTML=opts(state.stores);
  $('central-store').value=store.store_id;
  $('central-view').innerHTML=views.map(([key,name])=>selectOption(key,name)).join('');
  $('central-mode').textContent=state.mode==='demo'?'独立演练 · 使用合成数据':'使用当前门店权限与中央台账';
  document.querySelector('[data-tab="central"]').hidden=false;
  $('central-store').onchange=()=>{
    if(state.camStream)stopCamera();
    central.planId='';
    central.shipmentId='';
    showCentralView();
  };
  $('central-view').onchange=()=>{
    if(state.camStream)stopCamera();
    if($('central-view').value==='labels'){
      const warehouse=state.stores.find(store=>store.kind==='warehouse');
      if(warehouse)$('central-store').value=warehouse.store_id;
    }
    showCentralView();
  };
  $('central-print-dialog').addEventListener('close',()=>{
    $('central-print-frame').removeAttribute('srcdoc');
    $('central-print-now').disabled=true;
    central.printLabels=null;
  });
}

async function centralRead(view,params={}){
  return centralData(await req(centralUrl('/central/'+view,{store_id:centralStore(),...params})));
}

// Only the random request ID and a digest stay in this tab after an uncertain result.
const centralRequestIds = new Map();
async function centralRequestKey(path,body){
  const bytes=new TextEncoder().encode(JSON.stringify([state.me.employee_id,path,body]));
  const hash=await crypto.subtle.digest('SHA-256',bytes);
  return 'bsv-sup59-'+[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
function requestIdFor(key){
  let id=centralRequestIds.get(key);
  if(!id){
    try{id=sessionStorage.getItem(key);}catch{}
    if(!id)id=uid();
    centralRequestIds.set(key,id);
    try{sessionStorage.setItem(key,id);}catch{}
  }
  return id;
}
function releaseRequestId(key){
  centralRequestIds.delete(key);
  try{sessionStorage.removeItem(key);}catch{}
}
async function centralWrite(action,body){
  const path='/central/'+action;
  const key=await centralRequestKey(path,body);
  const request_id=requestIdFor(key);
  try{
    const result=await req(path,{method:'POST',body:JSON.stringify({request_id,...body}),raw:true});
    if(result.state!==(state.mode==='demo'?'DEMO_COMMITTED':'COMMITTED'))throw Error('台账尚未确认。请核对记录；同一表单重试会复用原请求。');
    releaseRequestId(key);
    return {...centralData(result),request_id:result.request_id??request_id};
  }catch(error){
    if([401,403,404,422].includes(error.status))releaseRequestId(key);
    throw error;
  }
}

function busyCentral(control,callback){
  return async event=>{
    event?.preventDefault();
    if($('central-content').dataset.busy==='true')return;
    if(state.camStream)stopCamera();
    const inputs=[...$('central-content').querySelectorAll('input,select,button,textarea'),$('central-store'),$('central-view')].filter(x=>!x.disabled);
    const values=control instanceof HTMLFormElement?Object.fromEntries(new FormData(control)):null;
    $('central-content').dataset.busy='true';
    inputs.forEach(x=>x.disabled=true);
    try{await callback(values);}
    catch(error){message(error.message,true);}
    finally{
      inputs.forEach(x=>x.disabled=false);
      $('central-content').dataset.busy='false';
    }
  };
}

async function showCentralView(){
  if(!state.centralCandidate||state.mode==='internal-stage')return;
  const revision=++central.revision;
  const content=$('central-content');
  const current=()=>revision===central.revision;
  const view=$('central-view').value;
  $('central-summary').textContent='';
  content.textContent='正在读取…';
  try{
    if(view==='plan')await showCentralPlan(current);
    if(view==='shipment')await showCentralShipments(current);
    if(view==='inventory'||view==='labels')await showCentralInventory(view,current);
    if(view==='tasks')await showCentralTasks(current);
    if(view==='exceptions')await showCentralExceptions(current);
  }catch(error){
    if(current()){
      content.innerHTML='<p role="alert"></p><button type="button">重试读取</button>';
      content.querySelector('p').textContent=error.message;
      content.querySelector('button').onclick=showCentralView;
    }
  }
}

function goodsOption(){
  return state.items.map(item=>selectOption(item.item_id,item.name_zh||item.item_id)).join('');
}
function ownSource(){
  const scope=state.me.role_stores?.dispatch;
  const stores=state.stores.filter(x=>!scope||scope.includes(x.store_id));
  return opts(stores,'选择发货网点');
}

async function showCentralPlan(current){
  const scope=state.me.role_stores?.dispatch;
  const source=state.stores.find(store=>store.kind==='warehouse'&&(!scope||scope.includes(store.store_id)));
  const planStore=source?.store_id??centralStore();
  const result=await centralRead('plans',{store_id:planStore});
  const plans=centralEntries(result,'plans').filter(plan=>!plan.batch_id&&plan.dest_store_id===centralStore());
  if(!current())return;
  const content=$('central-content');
  const form1 = fieldGroup('补货建议 · 调往 '+escapeHtml(centralName(centralStore())),`
    <div class="grid2">${selectField('source_store_id','生产点',ownSource())}
      ${selectField('item_id','物料',goodsOption())}
      ${formInput('next_delivery_at','下次送达时间（北京时间）','datetime-local')}
      ${formAmount('usage_before_next','下次配送前预计消耗')}
      ${formAmount('reserved','预留量')}
      ${formAmount('demand_next_cycle','下周期需求量')}
      ${formAmount('safety_stock','安全库存')}</div>
    <p class="hint">数量使用同一物料的批准基础单位。库存、在途及到期量由台账读取。</p>
    <div class="actions"><button id="central-plan-preview" type="submit">计算建议</button><button id="central-plan-save" type="submit" class="primary" disabled>确认计划</button></div>`);
  const planOptions=plans.map(plan=>selectOption(plan.plan_id??plan.id,`${plan.plan_id??plan.id} · ${plan.item_id||''}`)).join('');
  const form2=fieldGroup('制作与逐瓶分装',`
    <div class="grid2">${selectField('known_plan','已确认计划',selectOption('','输入其他计划编号')+planOptions,false)}
      ${formInput('plan_id','计划编号')}
      ${formInput('produced_at','实际制作时间（北京时间）','datetime-local')}
      ${formInput('recipe_version','批准配方版本')}
      ${formAmount('total','总产量','')}
      ${formAmount('remainder','剩余量')}
      ${formAmount('loss','损耗')}</div>
    ${manualIds('ingredient_lot_ids','实际使用的原料批次',true)}
    ${manualIds('package_amounts','逐瓶填入实装量',true)}
    <p class="hint">逐瓶装量 + 剩余量 + 损耗必须等于总产量。</p>${submitButton('确认制作和放行')}`);
  content.innerHTML=`<form id="central-plan-form">${form1}</form><div id="central-plan-result" aria-live="polite"></div>
    <form id="central-batch-form">${form2}</form>`;
  const planForm=$('central-plan-form');
  const batchForm=$('central-batch-form');
  let previewed;
  let planReady=false;
  if(source)planForm.elements.source_store_id.value=source.store_id;
  planForm.oninput=()=>{planReady=false;$('central-plan-save').disabled=true;};
  planForm.onsubmit=async event=>{
    const confirmPlan=event.submitter?.id==='central-plan-save';
    await busyCentral(planForm,async values=>{
      const body={...values,dest_store_id:centralStore(),next_delivery_at:localDateTime(values.next_delivery_at)};
      const serialized=JSON.stringify(body);
      if(confirmPlan){
        if(serialized!==previewed)throw Error('请先按当前输入重新计算补货建议。');
        const result=await centralWrite('plan',body);
        central.planId=result.plan_id??result.id;
        batchForm.elements.plan_id.value=central.planId;
        batchForm.elements.recipe_version.value=result.recipe_version??'';
        planReady=false;
        message('已确认制作计划 '+central.planId);
        return;
      }
      planReady=false;
      const result=centralData(await req('/central/plan-preview',{method:'POST',body:JSON.stringify(body)}));
      previewed=serialized;
      const recommendation=result.recommendation??result;
      const entries=[
        ['可用库存',result.confirmed_available??result.available],
        ['有效在途',result.eligible_in_transit??result.arrivals_before_next??result.in_transit],
        ['配送前到期',result.expires_before_arrival??result.expiry_before_next],
        ['建议包装数',recommendation.suggested_packs??recommendation.recommended_packs??recommendation.packages??recommendation.packs],
        ['建议生产量',recommendation.suggested_qty??recommendation.recommended_qty??recommendation.qty_base??recommendation.qty??recommendation.quantity],
        ['基础单位',result.unit],
        ['批准配方',result.recipe_version],
        ['状态',recommendation.reason??zhCentral(recommendation.status)]
      ];
      $('central-plan-result').innerHTML=centralTable(['补货核对项','结果'],
        entries.filter(([,value])=>value!=null).map(([name,value])=>[name,escapeHtml(value)]));
      planReady=(recommendation.status==='SUGGESTED'&&Number(recommendation.packages??recommendation.packs??recommendation.suggested_packs)>0);
    })(event);
    $('central-plan-save').disabled=!planReady;
  };
  const fillPlan=()=>{
    const plan=plans.find(x=>(x.plan_id??x.id)===batchForm.elements.known_plan.value);
    batchForm.elements.plan_id.value=batchForm.elements.known_plan.value;
    if(plan?.recipe_version)batchForm.elements.recipe_version.value=plan.recipe_version;
  };
  batchForm.elements.known_plan.onchange=fillPlan;
  batchForm.elements.plan_id.value=central.planId;
  batchForm.elements.produced_at.value=localNow();
  if(state.mode==='demo'){
    batchForm.elements.recipe_version.placeholder='DEMO-RECIPE-1';
    batchForm.elements.ingredient_lot_ids.placeholder='DEMO-LOT-1 或 DEMO-LOT-2（演练）';
  }
  batchForm.onsubmit=busyCentral(batchForm,async values=>{
    const {known_plan, ...data}=values;
    const result=await centralWrite('batch',{
      ...data,produced_at:localDateTime(values.produced_at),
      ingredient_lot_ids:centralList(values.ingredient_lot_ids),package_amounts:centralList(values.package_amounts)
    });
    message('已放行批次 '+result.batch_id+'，共 '+(result.packages??[]).length+' 件。可进入物料标签打印。');
    batchForm.reset();
    batchForm.elements.plan_id.value=central.planId;
    batchForm.elements.produced_at.value=localNow();
  });
}

async function showCentralShipments(current){
  const store=centralStore();
  const shipments=centralEntries(await centralRead('shipments'),'items');
  if(!current())return;
  const content=$('central-content');
  const canDispatch=workspace==='hq'&&centralRoles('dispatch');
  const options=shipments.map(x=>selectOption(x.id,`${x.id} · ${centralName(x.src)} → ${centralName(x.dest)} · ${zhCentral(x.state)}`)).join('');
  content.innerHTML=`
    <form id="central-shipment-lookup">
      ${fieldGroup('查看配送单',`<div class="grid2">${selectField('known_ship','已有配送',selectOption('','按配送单号查找')+options,false)}
      ${formInput('shipment_id','配送单号')}</div>${submitButton('打开配送单')}`)}
    </form>
    <div id="central-shipment-details"></div>
    ${canDispatch?`<form id="central-shipment-create">
      ${fieldGroup('新建配送草稿 · 送往 '+escapeHtml(centralName(store)),`<div class="grid2">
        ${selectField('source_store_id','发货网点',ownSource())}
        ${formInput('eta','预计送达（北京时间）','datetime-local')}</div>
        ${manualIds('package_ids','已放行包装码（扫码或手输）',true)}<div class="actions"><button id="central-scan-create" type="button">相机扫码</button>${submitButton('创建配送草稿')}</div>`)}
    </form>`:''}`;
  const lookup=$('central-shipment-lookup');
  lookup.elements.known_ship.onchange=()=>{lookup.elements.shipment_id.value=lookup.elements.known_ship.value;};
  lookup.elements.shipment_id.value=central.shipmentId;
  const load=async id=>{
    const result=await centralRead('shipment',{shipment_id:id});
    if(!current())return;
    central.shipmentId=id;
    renderCentralShipment(result);
  };
  lookup.onsubmit=busyCentral(lookup,async values=>{
    await load(values.shipment_id.trim());
  });
  if(canDispatch){
    const create=$('central-shipment-create');
    const warehouse=state.stores.find(store=>store.kind==='warehouse'&&[...create.elements.source_store_id.options].some(option=>option.value===store.store_id));
    if(warehouse)create.elements.source_store_id.value=warehouse.store_id;
    $('central-scan-create').onclick=()=>scanCentralList(create.elements.package_ids);
    create.onsubmit=busyCentral(create,async values=>{
      const result=await centralWrite('create',{
        source_store_id:values.source_store_id,dest_store_id:store,
        package_ids:centralList(values.package_ids),eta:localDateTime(values.eta)
      });
      lookup.elements.shipment_id.value=result.id;
      create.reset();
      if(warehouse)create.elements.source_store_id.value=warehouse.store_id;
      message('已创建配送单 '+result.id);
      await load(result.id);
    });
  }
  if(central.shipmentId){
    try{await load(central.shipmentId);}
    catch(error){if(current())message(error.message,true);}
  }
}

function renderCentralShipment(shipment){
  const detail=$('central-shipment-details');
  const id=shipment.id??shipment.shipment_id;
  const packs=shipment.planned??shipment.packages??[];
  const receipts=new Map((shipment.receipts??[]).map(row=>[row.package?.package_id??row.package_id,row]));
  const prepare=shipment.state==='DRAFT';
  const dispatch=['READY','FOR_DISPATCH'].includes(shipment.state);
  const receive=['DISPATCHED','IN_TRANSIT','PARTIAL_RECEIVED','DISPUTED'].includes(shipment.state);
  const canDispatch=centralRoles('dispatch')&&workspace==='hq';
  const canReceive=centralRoles('receive')&&centralStore()===shipment.dest;
  const displayRows=packs.map((p,i)=>{
    const code=p.package_id??p.code;
    const receipt=receipts.get(code);
    const pending=!receipt&&receive&&canReceive;
    const expired=p.expires_at&&Date.parse(p.expires_at)<=Date.now();
    return [
      escapeHtml(code),escapeHtml(p.name??p.item_id),escapeHtml(`${p.amount??'—'} ${p.unit??''}`),
      escapeHtml(beijingTime(p.expires_at)),escapeHtml(zhCentral(receipt?.condition??receipt?.status??receipt?.package?.state??p.state))+(receipt?`<br><span class="meta">${escapeHtml(receipt.receiver_id??'')} ${escapeHtml(beijingTime(receipt.received_at))} ${escapeHtml(receipt.exception_reason??p.recall_reason??'')}</span>`:''),
      pending?`<select name="receipt-${i}" data-receipt-index="${i}" aria-label="签收结果 ${escapeHtml(code)}">
        <option value="">本次未收到</option><option value="ACCEPTED" ${expired?'disabled':''}>合格</option><option value="HOLD">隔离</option>
      </select>`:'—',
      pending?`<input name="reason-${i}" maxlength="180" aria-label="异常原因 ${escapeHtml(code)}" placeholder="隔离时必填">`:'—'
    ];
  });
  detail.innerHTML=`<form id="central-shipment-action">
    ${fieldGroup('配送单 '+escapeHtml(id),`<p>${escapeHtml(centralName(shipment.src))} → ${escapeHtml(centralName(shipment.dest))} · ${escapeHtml(zhCentral(shipment.state))}</p>
      <p class="meta">预计 ${escapeHtml(beijingTime(shipment.eta))} · 实发 ${escapeHtml(beijingTime(shipment.sent_at))} · 发货人 ${escapeHtml(shipment.sender_id||'—')} · 实到 ${escapeHtml(beijingTime(shipment.arrived_at))}</p>
      ${centralTable(['包装码','物料','装量','死期','状态','本次实收','异常原因'],displayRows)}
      ${receive&&canReceive?`<div class="grid2">${formInput('receipt_scan','扫码确认一件','text','autocomplete="off"')}
        <div class="actions"><button id="central-add-receipt" type="button">标记扫码件为合格</button>
        <button id="central-scan-receipt" type="button">相机扫码</button></div></div>`:''}
      ${dispatch&&canDispatch?`${manualIds('scanned_codes','实际发货扫码清单',true)}
        <button id="central-scan-dispatch" type="button">相机扫码</button>`:''}
      <div class="actions">
        ${prepare&&canDispatch?submitButton('确认备货'):''}
        ${dispatch&&canDispatch?submitButton('确认发货'):''}
        ${receive&&canReceive?submitButton('确认本次签收'):''}
        ${receipts.size?`<button id="central-arrival-print" type="button">打印 A4 到货清单</button>`:''}
      </div>`)}
    </form>`;
  const form=$('central-shipment-action');
  if(dispatch&&canDispatch)$('central-scan-dispatch').onclick=()=>scanCentralList(
    form.elements.scanned_codes,new Set(packs.map(p=>p.package_id??p.code))
  );
  if(receive&&canReceive){
    const mark=(raw,manual=true)=>{
      const code=raw.trim();
      if(!code)return;
      const index=packs.findIndex(item=>(item.package_id??item.code)===code);
      const select=index>=0&&form.elements['receipt-'+index];
      if(!select){if(manual)message('包装不在本单待签收清单。',true);return;}
      if(select.options[1].disabled){select.value='HOLD';message('这件物料已到死期，请记录隔离原因。',true);}
      else if(select.value!=='HOLD')select.value='ACCEPTED';
      if(manual){form.elements.receipt_scan.value='';form.elements.receipt_scan.focus();}
    };
    const markField=()=>mark(form.elements.receipt_scan.value);
    $('central-add-receipt').onclick=markField;
    $('central-scan-receipt').onclick=()=>startCamera(code=>mark(code,false));
    form.elements.receipt_scan.onkeydown=event=>{
      if(event.key==='Enter'){event.preventDefault();markField();}
    };
  }
  if(receipts.size)$('central-arrival-print').onclick=busyCentral($('central-arrival-print'),()=>showCentralPrint('arrival',{shipment_id:id}));
  if(!(prepare&&canDispatch||dispatch&&canDispatch||receive&&canReceive))return;
  form.onsubmit=busyCentral(form,async values=>{
    if(values.receipt_scan?.trim())throw Error('请先在本次实收中确认输入的包装码。');
    const body={shipment_id:id,expected_version:shipment.version};
    if(dispatch)body.scanned_codes=centralList(values.scanned_codes);
    if(receive){
      body.accepted_ids=[];
      body.hold_ids=[];
      body.exception_reasons={};
      for(const [index,p] of packs.entries()){
        const code=p.package_id??p.code;
        if(values['receipt-'+index]==='ACCEPTED')body.accepted_ids.push(code);
        if(values['receipt-'+index]==='HOLD'){
          const reason=values['reason-'+index]?.trim();
          if(!reason)throw Error('请写明每个隔离包装的原因。');
          body.hold_ids.push(code);
          body.exception_reasons[code]=reason;
        }
      }
      if(!body.accepted_ids.length&&!body.hold_ids.length)throw Error('请至少核对一件本次实收包装。');
    }
    await centralWrite(prepare?'prepare':dispatch?'dispatch':'receive',body);
    message(prepare?'备货已提交。':dispatch?'发货已提交。':'本次实收已提交。未确认件保持在途。');
    await showCentralView();
  });
}

function scanCentralList(input,allowed){
  return startCamera(raw=>{
    const code=raw.trim();
    if(!/^[A-Za-z0-9_-]{1,100}$/.test(code)||allowed&&!allowed.has(code))return;
    const codes=centralList(input.value);
    if(!codes.includes(code))input.value=[...codes,code].join('\n');
  });
}

function packageDescription(p){
  return escapeHtml(p.name||p.item_id)+'<br><span class="meta">'+escapeHtml(p.package_id)+'</span>';
}
function packageState(p){
  if(p.state==='ACCEPTED'&&Number(p.remaining)===0)return '已用完';
  if(p.state==='HOLD'||p.state==='SCRAPPED')return zhCentral(p.state);
  return p.expires_at&&Date.parse(p.expires_at)<=Date.now()?'已过期':zhCentral(p.state);
}

async function showCentralInventory(view,current){
  const store=centralStore();
  const snapshot=await centralRead('inventory');
  if(!current())return;
  const content=$('central-content');
  const packages=centralEntries(snapshot,'packages');
  const labels=view==='labels';
  const eligible=labels?packages.filter(p=>p.state==='READY'&&packageState(p)!=='已过期'):packages;
  const scoped=state.me.role_stores?.receive;
  const mayUpdate=!labels&&centralRoles('receive')&&(!scoped||scoped.includes(store));
  const dispatchScope=state.me.role_stores?.dispatch;
  const mayRecall=!labels&&workspace==='hq'&&centralRoles('dispatch')&&(!dispatchScope||dispatchScope.includes(store));
  const rows=eligible.map(p=>[
    labels?`<label class="check-line"><input type="checkbox" name="label-package" value="${escapeHtml(p.package_id)}">${packageDescription(p)}</label>`:packageDescription(p),
    escapeHtml(p.batch_id),escapeHtml(`${p.remaining} / ${p.amount} ${p.unit}`),escapeHtml(beijingTime(p.expires_at)),
    `<span class="state ${['HOLD','SCRAPPED'].includes(p.state)||packageState(p)==='已过期'?'bad-stock':''}">${escapeHtml(packageState(p))}</span>`,
    escapeHtml(p.storage),escapeHtml(p.usage),
    mayUpdate||mayRecall?`<div class="actions">
      ${mayUpdate&&p.state==='ACCEPTED'&&!p.opened_at&&p.usable===true?`<button type="button" data-package="${escapeHtml(p.package_id)}" data-package-action="open">登记开封</button>`:''}
      ${mayUpdate&&p.opened_at&&p.usable===true?`<button type="button" data-package="${escapeHtml(p.package_id)}" data-package-action="consume">登记实际耗用</button>`:''}
      ${mayUpdate&&(p.state==='HOLD'||p.state==='ACCEPTED'&&packageState(p)==='已过期')&&Number(p.remaining)>0?`<button type="button" data-package="${escapeHtml(p.package_id)}" data-package-action="dispose">登记报损／处置</button>`:''}
      ${mayRecall&&['READY','ACCEPTED','IN_TRANSIT'].includes(p.state)&&Number(p.remaining)>0?`<button type="button" data-package="${escapeHtml(p.package_id)}" data-package-action="recall">召回</button>`:''}
    </div>`:escapeHtml(beijingTime(p.produced_at))
  ]);
  const table=centralTable([labels?'选择包装':'包装','批次','余量 / 实装','死期','状态','储存','使用说明',mayUpdate||mayRecall?'操作':'制作时间'],rows);
  $('central-summary').textContent=snapshot.revision==null?'':`清单版本 ${snapshot.revision}`;
  content.innerHTML=labels?`<form id="central-label-form">${table}
    ${manualIds('extra_ids','或输入包装码（查询历史、确认已发出包装）')}
    ${formInput('print_request_id','原打印请求编号（确认实物时填写）','text','maxlength="36" autocomplete="off"')}
    <div class="actions">
    <button class="primary" type="submit" data-operation="PRINT">准备打印</button>
    <button type="submit" data-operation="REPRINT">准备重印</button>
    <button type="submit" data-operation="CONFIRM">确认实物已印</button>
    <button type="button" id="central-label-history">查看所选打印记录</button></div>
    <p class="hint">在打印窗口选 50 × 40 mm 和实际大小。核对实物与二维码后，再确认已经打印。</p></form>
    <div id="central-label-history-list"></div>`:
    `<div class="actions"><button type="button" id="central-expiry-print">打印 A4 效期与处置清单</button></div>
      ${table}<div id="central-stock-action"></div>`;
  if(labels){
    const form=$('central-label-form');
    form.elements.print_request_id.value=central.lastPrintByStore.get(store)??'';
    const selected=()=>[...new Set([...new FormData(form).getAll('label-package'),...centralList(form.elements.extra_ids.value)])];
    const history=async ids=>{
      const result=await centralRead('labels',{package_ids:ids});
      const events=result.history??result.print_history??[];
      const rendered=events.map(row=>[
        escapeHtml(row.package_id),
        escapeHtml(zhCentral(row.operation)),
        escapeHtml(row.actor_id??row.employee_id),
        escapeHtml(row.request_id),
        escapeHtml(beijingTime(row.occurred_at??row.created_at))
      ]);
      $('central-label-history-list').innerHTML=centralTable(['包装码','操作','经办人','请求编号','时间'],rendered);
    };
    form.onsubmit=event=>{
      const ids=selected();
      const operation=event.submitter?.dataset.operation;
      busyCentral(form,async values=>{
        if(!ids.length||!operation)throw Error('请先选择至少一个包装。');
        if(operation==='CONFIRM'){
          const print_request_id=values.print_request_id.trim();
          if(!print_request_id)throw Error('请从打印记录中复制原打印请求编号。');
          if(!window.confirm('确认已核对选定包装的实际标签和二维码。'))return;
          await centralWrite('label',{store_id:store,package_ids:ids,operation,print_request_id});
          message('已确认实物标签。');
          await history(ids);
          return;
        }
        const html=await req(centralUrl('/central/print/labels',{store_id:store,package_ids:ids}),{response:'html'});
        central.printLabels={store_id:store,package_ids:ids,operation};
        openCentralPrint(html);
      })(event);
    };
    $('central-label-history').onclick=event=>{
      const ids=selected();
      busyCentral($('central-label-history'),async ()=>{
        if(!ids.length)throw Error('请先选择至少一个包装。');
        await history(ids);
      })(event);
    };
    return;
  }
  $('central-expiry-print').onclick=busyCentral($('central-expiry-print'),()=>showCentralPrint('expiry'));
  for(const button of content.querySelectorAll('[data-package-action]')){
    button.onclick=()=>showStockAction(eligible.find(p=>p.package_id===button.dataset.package),button.dataset.packageAction);
  }
}

function showStockAction(p,action){
  if(!p)return;
  const title={open:'登记实际开封',consume:'登记实际耗用',dispose:'登记实际处置',recall:'召回与隔离'}[action];
  let fields;
  if(action==='open')fields='<p>提交后按服务端批准规则重新计算死期。</p>';
  if(action==='consume')fields=formAmount('amount','本次实际耗用量（'+escapeHtml(p.unit)+'）','');
  if(action==='dispose')fields=`<div class="grid2">${formAmount('amount','确认实际处置量（'+escapeHtml(p.unit)+'）','')}
      ${formInput('reason','实际处置原因','text','maxlength="180" required')}</div>`;
  if(action==='recall')fields=formInput('reason','召回原因','text','maxlength="180" required');
  $('central-stock-action').innerHTML=`<form id="central-stock-form">${fieldGroup(
    title+' · '+escapeHtml(p.package_id),fields+submitButton('确认'+title)
  )}</form>`;
  const form=$('central-stock-form');
  form.scrollIntoView({block:'nearest'});
  form.onsubmit=busyCentral(form,async values=>{
    await centralWrite(action,{...values,package_id:p.package_id,expected_version:p.version,store_id:centralStore()});
    message({open:'已记录开封时间和新死期。',consume:'已登记实际耗用并更新余量。',dispose:'已登记实际处置。',recall:'已记录召回与隔离。'}[action]);
    await showCentralView();
  });
}

async function showCentralTasks(current){
  const content=$('central-content');
  const readTasks=async phase=>{
    const result=await centralRead('tasks',{phase});
    if(!current())return;
    const entries=centralEntries(result,'tasks');
    $('central-task-list').innerHTML=centralTable(['事项','包装／配送','时刻','说明'],entries.map(task=>[
      escapeHtml({
        EXPIRY_REVIEW:'核对物料效期',EXPIRED:'处理过期物料',DUE_TODAY:'当日到期',ARRIVAL:'预计到货',RECEIVE:'待签收',
        HANDOFF:'待交接',DISPOSAL:'待处置',EXCEPTION:'处理异常',NEW_ITEM:'查阅新品说明',
        RECEIPT_REVIEW:'到货及签收核对',USE_GUIDANCE:'物料使用说明'
      }[task.kind??task.type]??task.title??task.kind??task.type??task.task_key),
      escapeHtml(task.package_id??task.shipment_id??task.key),
      escapeHtml(task.due?.includes('周')?task.due:beijingTime(task.due_at??task.due??task.eta??task.expires_at)),
      escapeHtml([task.description??task.usage??task.reason??task.detail,task.handover_required?'交给下一班':''].filter(Boolean).join(' · '))
    ]));
  };
  content.innerHTML=`<label>班次阶段<select id="central-phase"><option value="START">上班</option>
    <option value="END">下班</option></select></label><div id="central-task-list"></div>
    <p class="hint">请在配送或库存页面记录实际处理结果。此页查询不产生考勤记录。</p>`;
  $('central-phase').onchange=busyCentral($('central-phase'),()=>readTasks($('central-phase').value));
  await readTasks('START');
}

async function showCentralExceptions(current){
  const result=await centralRead('exceptions');
  if(!current())return;
  const items=centralEntries(result,'items');
  $('central-content').innerHTML=centralTable(['异常类别','包装／配送','时刻','原因／状态'],items.map(row=>[
    escapeHtml({EXPIRED:'过期未处理',HOLD:'隔离',RECEIVE_PENDING:'待签收',DISPUTED:'配送差异',
      RECALL:'召回',SCRAPPED:'报损',REMEDIATION:'待整改',UNRECEIVED:'未签收'}[row.kind??row.type??row.state]??row.title??row.kind??row.type??row.state),
    escapeHtml(row.package_id??row.shipment_id??row.id),
    escapeHtml(beijingTime(row.occurred_at??row.due??row.eta??row.expires_at)),
    escapeHtml(row.reason??row.detail??zhCentral(row.state))
  ]));
}

async function showCentralPrint(kind,params={}){
  const html=await req(centralUrl('/central/print/'+kind,{store_id:centralStore(),...params}),{response:'html'});
  central.printLabels=null;
  openCentralPrint(html);
}
function openCentralPrint(html){
  if(typeof html!=='string')throw Error('暂时没有可打印版式。');
  const frame=$('central-print-frame');
  const button=$('central-print-now');
  button.disabled=true;
  $('central-print-feedback').textContent='';
  frame.onload=()=>{button.disabled=false;};
  frame.srcdoc=html;
  button.onclick=async ()=>{
    button.disabled=true;
    try{
      if(central.printLabels){
        const command=central.printLabels;
        const result=await centralWrite('label',command);
        central.lastPrintByStore.set(command.store_id,result.request_id);
        const confirmation=$('central-label-form')?.elements.print_request_id;
        if(confirmation)confirmation.value=result.request_id??'';
        central.printLabels=null;
      }
      frame.contentWindow.print();
    }catch(error){$('central-print-feedback').textContent=error.message;}
    finally{button.disabled=false;}
  };
  $('central-print-dialog').showModal();
}
