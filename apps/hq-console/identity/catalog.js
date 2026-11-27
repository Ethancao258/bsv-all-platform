"use strict";
const $=id=>document.getElementById(id);
const labels={C:"现场成品",K:"套餐组合",P:"预调半成品",M:"采购纯饮",R:"配方耗用",Q:"门店报价",T:"门店注册"};
const statusLabels={PENDING_REVIEW:"待另一位管理员审核",REVIEWED_NOT_PUBLISHED:"已审核 · 未发布",VERIFIED_PACKAGE_NOT_PUBLISHED:"候选规范包已校验 · 未发布",RELEASE_REQUESTED:"待受控签名执行",RAW_REVISION_ACTIVE:"原始资料已写入中央数据库 · 销售版本未改变",SALE_ACTIVE:"销售版本已生效 · POS及酒单源站已更新",RELEASE_BLOCKED:"发布未执行 · 需要处理",RELEASE_RECONCILIATION_REQUIRED:"发布结果待核对 · 请勿重试",REJECTED:"已拒绝",IDEMPOTENT_NOOP:"与当前版本相同",PREVIEW_ONLY:"预览完成 · 未写入"};
const fieldsFor={C:["商品名称","销售系列","配方文字","完整制作步骤","标注售价"],K:["套餐名称"],P:["半成品名称","完整制作步骤"],M:["物料名称"],R:["工序名称","完整制作步骤"],Q:["核准售价","币种","销售渠道","生效日期","失效日期"],T:[]};
const forbidden=new Set(["商品ID","半成品ID","物料ID","套餐ID","门店ID"]);
let active="",offset=0,selected=null,excel=null,allowedFields=[],caps={},actor="";
const kindLabels={edit:"修改资料",create:"新增资料",excel:"Excel批量修改",retire:"退役申请",rollback:"版本恢复",sale:"商品上下架"};
const csrf=()=>decodeURIComponent((document.cookie.split("; ").find(x=>x.startsWith("bsv_csrf="))||"").split("=").slice(1).join("="));
function say(s,error=false){$("notice").textContent=s;$("notice").className=error?"error":"";}
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
async function call(path,method="GET",body=null,raw=false){
 const headers={Accept:"application/json"};
 if(method!=="GET"){headers["X-CSRF-Token"]=csrf();headers["Content-Type"]=raw?"application/octet-stream":"application/json";}
 const response=await fetch("/api/v1/hq/catalog"+path,{method,headers,credentials:"same-origin",body:body===null?null:raw?body:JSON.stringify(body)});
 let data;try{data=await response.json();}catch{throw Error("服务暂不可用（"+response.status+"）");}
 if(!response.ok)throw Error(data.detail?.message||data.error?.message||"操作被拒绝（"+response.status+"）");
 return data;
}
function run(fn){return async e=>{e?.preventDefault();try{await fn();}catch(err){say(err.message||"操作失败",true);}};}
async function refresh(){
 active="";excel=null;$("submitExcel").disabled=true;$("source").textContent="正在核验";
 const data=await call("/status");active=data.active_sha256;caps=data.capabilities||{};actor=data.actor;
 $("salePanel").hidden=!caps.sale||!caps.draft;
 $("preview").disabled=!caps.draft;$("file").disabled=!caps.draft;$("rollback").querySelector("button").disabled=!caps.draft;
 $("loadDrafts").disabled=!caps.draft&&!caps.review;
 $("source").textContent="活动版本："+active+" · 当前管理者："+data.actor;
 $("counts").replaceChildren(...Object.keys(labels).map(k=>{let box=el("div",labels[k]);box.append(el("strong",data.counts[k]??0));return box;}));
 offset=0;await records();say(data.activation==="PRODUCTION"?"正式目录活动版本已核验。":"活动版本已核验；隔离模式不执行销售发布。");
}
async function records(){
 if(!active)throw Error("请先核验活动版本。");
 const domain=$("domain").value;
 const d=await call("/records?"+new URLSearchParams({domain,q:$("search").value,offset}));
 if(active!==d.active_sha256)throw Error("活动版本已改变，请刷新。");
 allowedFields=d.editable_fields||[];
 $("total").textContent="共 "+d.total+" 条 · 第 "+(offset+1)+"–"+Math.min(offset+100,d.total)+" 条";
 $("prev").disabled=offset===0;$("next").disabled=offset+100>=d.total;
 $("records").replaceChildren(...d.items.map(row=>{let b=el("button",row.id+"  "+row.name);b.type="button";b.className="catalog-record secondary";b.onclick=()=>selectRow(row);return b;}));
 if(!d.items.length)$("records").append(el("p","没有匹配资料。"));
 selected=null;renderEdit();
}
function selectRow(row){selected=row;$("kind").value="edit";renderEdit();}
function renderEdit(){
 const kind=$("kind").value,domain=$("domain").value,readOnly=domain==="T";
 $("record").value=kind==="create"?"":selected?.id||"";
 $("editTitle").textContent=kind==="create"?"新增 "+labels[domain]+"（永久ID待分配）":selected?.name||"选择资料";
 $("fields").replaceChildren();
 if(kind!=="retire"){
  const entries=kind==="create"?allowedFields.map(k=>[k,""]):Object.entries(selected?.fields||{}).filter(([k])=>allowedFields.includes(k));
  for(const [k,v] of entries){const label=el("label",k),input=el("textarea");input.rows=2;input.maxLength=4000;input.dataset.field=k;input.value=v??"";input.dataset.original=input.value;label.append(input);$("fields").append(label);}
 }
 $("submitEdit").disabled=readOnly||!allowedFields.length||(!selected&&kind!=="create");$("newBtn").disabled=readOnly||!allowedFields.length;
}
async function draft(){
 const kind=$("kind").value,fields={};for(const x of $("fields").querySelectorAll("textarea"))if(x.value.trim()&&(kind==="create"||x.value!==x.dataset.original))fields[x.dataset.field]=x.value;
 const result=await call("/drafts","POST",{kind,baseline_sha256:active,domain:$("domain").value,record_id:kind==="create"?"":$("record").value,fields,reason:$("reason").value});
 say("草稿已提交："+result.id+"；未生效。");$("reason").value="";await drafts();
}
async function preview(){
 excel=null;$("submitExcel").disabled=true;$("diff").replaceChildren();
 const file=$("file").files[0];if(!file||!file.name.toLowerCase().endsWith(".xlsx"))throw Error("请选择.xlsx文件。");
 if(file.size>4*1024*1024)throw Error("文件超过当前4 MiB上限。");
 const d=await call("/preview","POST",file,true);
 if(d.baseline_sha256!==active||$("file").files[0]!==file)throw Error("活动版本或所选文件已改变，请重新预览。");
 excel={file,data:d};$("diff").append(el("h3",statusLabels[d.status]||d.status));
 for(const [key,label] of [["added","新增"],["modified","修改"],["pending_retire","待退役"],["formula_cells","公式变化"]]){
 const rows=d.changes[key]||[];$("diff").append(el("p",label+"："+rows.length));for(const x of rows.slice(0,50))$("diff").append(el("p",typeof x==="string"?x:x.sheet+" / "+x.record_id+" "+(x.changed_fields||[]).join("、")));
 if(rows.length>50)$("diff").append(el("p","仅展示前50条；总数如上。"));
 }
 renderCellReview($("diff"),d.changes.cell_review);
 $("submitExcel").disabled=!d.review_ready||d.status==="IDEMPOTENT_NOOP";say("预览完成，未写入商品主库。");
}
function renderCellReview(box,review){if(!review)return;box.append(el("h3","逐格差异 · "+review.total+"处"));for(const x of review.cells||[]){box.append(el("p",x.address+" · "+x.field+"： "+String(x.before??"空")+" → "+String(x.after??"空")+(x.formula_cache?"（公式缓存，未验证计算）":"")));}if(review.blocked_count){box.append(el("p","受保护或未登记变更："+review.blocked_count));for(const x of review.blocked||[])box.append(el("p",x));}if(review.truncated)box.append(el("p","超过单次300处可完整审核上限，请拆分批次。"));}
async function drafts(){
 const d=await call("/drafts");$("drafts").replaceChildren();
 for(const x of d.items){const box=el("div");box.className="catalog-entry";box.append(el("strong",(statusLabels[x.status]||x.status)+" · "+(kindLabels[x.kind]||x.kind)+" · "+(x.record_id||x.id)),el("p","提交者："+x.created_by+" · "+x.created_at),el("p",x.reason));
 if(x.preview?.changes?.cell_review){const detail=el("details");detail.append(el("summary","查看完整逐格差异"));renderCellReview(detail,x.preview.changes.cell_review);box.append(detail);}
 if(x.fields)for(const [k,v] of Object.entries(x.fields)){const fact=x.sale_facts?.[k];box.append(el("p",fact?k+" · "+fact.name+" · "+(fact.price_cents===null?"无有效价格":"¥"+(fact.price_cents/100).toFixed(2))+" · "+(v==="LIST"?"上架":"下架"):k+"："+v));}
 if(x.status==="PENDING_REVIEW"&&caps.review&&x.created_by!==actor&&(x.kind!=="sale"||caps.sale)){let reason=el("textarea");reason.placeholder="审核理由（至少8字）";reason.maxLength=500;box.append(reason);
 for(const decision of ["approve","reject"]){let b=el("button",decision==="approve"?"审核通过（不发布）":"拒绝");b.type="button";b.onclick=run(async()=>{if(reason.value.trim().length<8)throw Error("请填写审核理由。");await call("/drafts/"+x.id+"/review","POST",{decision,reason:reason.value});say("审核已记录；未发布。");await drafts();});box.append(b);}}
 if(x.status==="REVIEWED_NOT_PUBLISHED"&&caps.review&&x.reviewed_by===actor&&["edit","excel","create"].includes(x.kind)){let b=el("button","生成待发布规范包");b.type="button";b.onclick=run(async()=>{await call("/drafts/"+x.id+"/prepare","POST",{});say("候选包已校验，尚未发布。");await drafts();});box.append(b);}
 if(caps.release&&x.reviewed_by===actor&&(x.status==="VERIFIED_PACKAGE_NOT_PUBLISHED"||(["rollback","sale"].includes(x.kind)&&x.status==="REVIEWED_NOT_PUBLISHED"))){let b=el("button",x.kind==="sale"?"确认发布至POS与顾客酒单":"申请资料生效（不自动上架）");b.type="button";b.onclick=run(async()=>{if(!confirm(x.kind==="sale"?"确认更新正式门店可售商品及顾客酒单？":"提交受控资料发布申请？销售版本暂不改变。"))return;await call("/drafts/"+x.id+"/release-request","POST",{});say("发布申请已登记，等待受控签名执行。");await drafts();});box.append(b);}
 if(x.package)box.append(el("p","候选包SHA："+x.package.archive_sha256));
 $("drafts").append(box);}
 if(!d.items.length)$("drafts").append(el("p","暂无草稿。"));
}
$("refresh").onclick=run(refresh);$("domain").onchange=run(async()=>{offset=0;$("kind").value="edit";await records();});
$("searchBtn").onclick=run(async()=>{offset=0;await records();});$("prev").onclick=run(async()=>{offset=Math.max(0,offset-100);await records();});$("next").onclick=run(async()=>{offset+=100;await records();});
$("newBtn").onclick=()=>{selected=null;$("kind").value="create";renderEdit();};$("kind").onchange=renderEdit;$("edit").onsubmit=run(draft);
$("preview").onclick=run(preview);$("file").onchange=()=>{excel=null;$("submitExcel").disabled=true;$("diff").replaceChildren();};
$("submitExcel").onclick=run(async()=>{if(!excel)throw Error("请先预览。");const {file,data}=excel;const d=await call("/excel-drafts?"+new URLSearchParams({sha:data.source_sha256,baseline:data.baseline_sha256}),"POST",file,true);$("submitExcel").disabled=true;say("Excel草稿已提交："+d.id+"；未发布。");await drafts();});
$("loadDrafts").onclick=run(drafts);$("loadVersions").onclick=run(async()=>{const d=await call("/versions");$("versions").replaceChildren();for(const x of d.items){const b=el("button",x.sha256+" · "+x.imported_at);b.type="button";b.className="catalog-record secondary";b.disabled=x.sha256===active;b.onclick=()=>{$("targetSha").value=x.sha256;$("rollbackReason").focus();};$("versions").append(b);}});$("rollback").onsubmit=run(async()=>{await call("/drafts","POST",{kind:"rollback",baseline_sha256:active,record_id:$("targetSha").value,reason:$("rollbackReason").value});say("恢复申请已提交；未切换活动版本。");await drafts();});
$("saleForm").onsubmit=run(async()=>{const fields={};for(const [id,action] of [["saleList","LIST"],["saleUnlist","UNLIST"]])for(const key of $(id).value.trim().split(/[\s,，、]+/).filter(Boolean)){if(fields[key])throw Error("同一编号重复或动作冲突："+key);fields[key]=action;}if(!Object.keys(fields).length)throw Error("请填写商品固定编号");const d=await call("/drafts","POST",{kind:"sale",domain:"C",baseline_sha256:active,fields,reason:$("saleReason").value});say("销售审批已提交："+d.id);await drafts();});
run(refresh)();
