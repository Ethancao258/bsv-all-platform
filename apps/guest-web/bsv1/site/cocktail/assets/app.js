/**
 * BAR ST. VINCENT｜顾客电子菜单 V13｜维护说明（请从这里开始）
 * =============================================================
 * 改商品数据 / 标注价 / 套餐：后台 V9 数据 → 对客 API；本文件不存商品资料。
 * 改云端 API 地址：assets/menu-config.js → catalogUrl。
 * 改界面文字（中/英）/酒精声明：assets/menu-copy.js → 对应 key。
 * 改颜色和动画时间：assets/style.css → :root 及 [MOTION_V11_NO_GHOST]。
 * 改分类按钮：下方 categories / categoryEn，以及 renderCats()。
 * 改筛选切换过渡：transitionMenu() / setScope()；搜索逐字输入不做延迟。
 * 改“帮我选”：renderRecommend() / beginRecommendation()。
 * 改产品卡片/详情：pCard() / renderDetail()。
 * 对接未来POS：window.BSVMenuBridge.getSelection() 只提供商品身份与数量；
 *              正式订单价格和支付状态必须在可信服务端计算及核验。
 * 强制边界：浏览器不得读取制作配方、人工成本、内部NPS等私有数据。
 * =============================================================
 */
'use strict';
const $ = id => document.getElementById(id);
const cfg = window.BSV_MENU_CONFIG || {catalogUrl:'./data/menu-public.json',defaultStoreId:'BSVM'};
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const categories=['环球精选','套餐与分享','佐酒与分享','经典调酒','本季特调','更多鸡尾酒','单品佳酿','饮品与甜点'];
const categoryEn={'环球精选':'Around the World','套餐与分享':'Sharing & Sets','佐酒与分享':'Bites & Sharing','经典调酒':'The Classics','本季特调':'Seasonal Creations','更多鸡尾酒':'More Cocktails','单品佳酿':'Fine Spirits','饮品与甜点':'Something Sweet'};
// All guest-visible UI phrases live in menu-copy.js; do not duplicate them here.
const words = window.BSV_MENU_COPY || {};
const state={data:null,lang:'zh',theme:'dark',store:'',scope:'all',search:'',filter:'全部',page:'menu',modal:null,detail:null,cart:{},cartStore:'',catalogFallback:false,
 recommend:{alcohol:'all',taste:'清爽',occasion:'慢慢品味'},recLoading:false,recRound:0,recShown:false};
const tr=k=>(words[k]||[k,k])[state.lang==='zh'?0:1];
/** [GUEST_TITLE] 仅清理展示用排版符号；数据库中的商品名称不改动。 */
const guestName=p=>String((state.lang==='en'&&p.name_en)?p.name_en:p.name||'').replace(/~~/g,'').replace(/（出品版）/g,'').replace(/\s+/g,' ').trim();
const categoryName=cat=>state.lang==='zh'?cat:(categoryEn[cat]||cat);
function normalize(s){return String(s??'').normalize('NFKC').toLowerCase().replace(/[，。！!、·•;；|/]+/g,' ').replace(/\s+/g,' ').trim()}
/** [CATALOG_ALL_ON_SHELF] 总部规则：C及K全部展示、均可加入选酒单（即便SKU待补全）。 */
function eligible(p){return p.kind==='prepared'||p.kind==='bundle';}
function items(){return (state.data?.items||[]).filter(eligible)}
function findProduct(id){return state.data?.items.find(p=>p.product_id===id)}
function storeName(){return state.data?.stores.find(s=>s.store_id===state.store)?.name||tr('store')}
function isPrice(v){return typeof v==='number'&&Number.isFinite(v)&&v>=0}
/**
 * [PRICE_V13_UNIFORM] 顾客菜单统一标价；不按门店代码查价。
 * C页成品唯一价格来源：C_现场成品!AJ「标注售价」→ reference_price.amount。
 * K页套餐没有C!AJ：由后台导出工具统一取「区域参考售价」，缺失再取「核心参考售价」。
 * 两类商品都不使用Q页各店报价，不访问price_by_store。
 * 缺价返回missing「到店询价」，仍可加入选酒单。任何实际付款须由BSV1后台核价。
 */
function priceData(p){
 const n=p.reference_price?.amount;
 return isPrice(n)?{kind:'listed',amount:n,label:tr(p.kind==='bundle'?'bundleMenuPrice':'listedPrice')}:{kind:'missing'};
}
const yuan=n=>'¥'+Number(n).toLocaleString('zh-CN',{maximumFractionDigits:2});
function priceInfo(p){const x=priceData(p);
 return x.kind==='missing'?{primary:tr('ask'),secondary:'',value:null}:{primary:yuan(x.amount),secondary:x.label,value:x.amount};
}
function priceDetails(p){const info=priceInfo(p);
 return `<div class="detail-price"><strong>${escapeHtml(info.primary)}</strong><span>${escapeHtml(info.secondary)}</span></div>`;
}
function categoryList(){return categories.filter(c=>items().some(p=>p.category===c))}
function labelOf(p){if(p.kind==='bundle')return '分享组合';const f=(p.flavor_tag||'').trim();return f&&f.length<=6?f:'';}
function concise(s,max=84){s=String(s||'').replace(/\s+/g,' ').trim().replace(/^这(?:款|杯)(?:酒|鸡尾酒)(?:整体)?(?:喝起来|口感|是)?/,'').replace(/^整体(?:口感|风味)?/,'');return s.length>max?s.slice(0,max).replace(/[，、；; ]+$/,'')+'…':s}
/** Fixed V13 editorial fallback keyed by immutable product_id; API approved public_flavor overrides it. */
const guestFlavorEdits={
 'C000001':'白兰地的醇厚与明亮柑橘相遇，酸爽利落，余韵干净。',
 'C000004':'薄荷的清凉遇上青柠的清爽，气泡轻快而明亮。',
 'C000003':'清透的柑橘酸香，轻盈干净，尾韵透出一丝辛香。',
 'C000006':'草本、花香与茶香逐层展开，蜂蜜甜意温柔收尾。',
 'C000007':'紫苏草本裹着李子、石榴与柠檬香，微微气泡轻轻跃动。',
 'C000008':'抹茶微苦衬出白巧克力的柔甜，奶香绵柔，像一份冷甜点。',
 'C000009':'青苹果与梅子般的清亮酸甜，轻盈爽口。',
 'C000010':'橙香与洋甘菊花香轻轻相遇，柔和酸甜被气泡托起。',
 'C000011':'绵密奶香与一丝柠檬酸度相衬，像可以慢慢品尝的甜点。',
 'C000012':'轻盈气泡托起柔和麦香与草本，留下一点淡淡枣甜。',
 'C000013':'蔓越莓与黑莓交织出明亮酸甜，入口清爽多汁。',
 'C000005':'蔓越莓的微酸与茉莉茶香交织，轻盈爽口。',
 'C000014':'樱桃与菠萝果香明亮，草本与香料为酸甜添上层次。',
 'C000024':'葡萄柚与蔓越莓轻轻碰撞，清爽微酸，像海边的一阵风。',
 'C000047':'外酥里软，薯香裹着黑松露的浓郁菌香，趁热更好吃。'
};
function flavorCopy(p){if(state.lang==='en')return p.name_en?(p.kind==='bundle'?'Discover this sharing set with our bartender.':'Ask our bartender about the flavor notes of this drink.'):tr('onlyChinese');
 if(p.kind==='bundle')return concise(p.description?parseBundleText(p.description).summary||p.contents||'适合一起分享的好时光。':p.contents||'和朋友一起，慢慢享受。',72);
 return concise((typeof p.public_flavor==='string'&&p.public_flavor.trim())?p.public_flavor:(guestFlavorEdits[p.product_id]||p.flavor||'来问问调酒师，这一杯会带来什么惊喜。'),100);
}
function safeStory(p){if(!p.story)return '';
 const s=p.story.trim();
 // Operational steps and training notes must not become customer stories.
 if(/(?:摇足|预调好的|提前调好|每杯只倒|先放|再放|加淡奶油|蛋白|基酒只放|兑上|最后放|改比例|操作|制作步骤|员工|培训|内部|SOP|SKU|后台)/i.test(s))return '';
 return s;
}
/** [PRODUCT_CARD] 商品卡片：中英文名称、口味、价格、分类标记。 */
function pCard(p){const priced=priceInfo(p,true);const label=labelOf(p);let desc=flavorCopy(p);
 const enSub=state.lang==='zh'?p.name_en||'':p.name_en?p.name:'';
 return `<button type="button" class="item ${p.kind==='bundle'?'bundle-item':''}" data-product="${escapeHtml(p.product_id)}" aria-label="${escapeHtml(guestName(p)+', '+priced.primary)}"><div class="item-copy"><div class="item-title"><strong>${escapeHtml(guestName(p))}</strong>${label?`<span class="item-label">${escapeHtml(label)}</span>`:''}</div>${enSub?`<div class="item-en">${escapeHtml(enSub)}</div>`:''}<div class="item-flavor">${escapeHtml(desc)}</div></div><div class="item-side"><div class="item-price ${priced.value===null&&priceData(p).kind==='missing'?'pending':''}">${escapeHtml(priced.primary)}</div>${priced.secondary?`<small>${escapeHtml(priced.secondary)}</small>`:''}<div class="item-arrow" aria-hidden="true">›</div></div></button>`;
}
/** [CATEGORY_BAR] 顶部分类横向导航的按钮列表。 */
function renderCats(){const cats=categoryList();$('categories').innerHTML=`<button type="button" class="cat-btn ${state.scope==='all'?'active':''}" data-category="all" aria-pressed="${state.scope==='all'}">${tr('all')}</button>`+cats.map(cat=>`<button type="button" class="cat-btn ${state.scope===cat?'active':''}" data-category="${escapeHtml(cat)}" aria-pressed="${state.scope===cat}">${escapeHtml(categoryName(cat))}</button>`).join('')}
function matchesSearch(p,query){
 const raw=normalize(query);if(!raw)return true;
 const hay=normalize([p.name,p.name_en,p.category,p.series,p.flavor,p.flavor_tag,guestFlavorEdits[p.product_id]||'',p.public_flavor||'',p.description,p.contents].join(' '));
 if(hay.includes(raw))return true;
 // Local keyword search: remove only common conversational filler, not product names.
 const simplified=normalize(raw.replace(/(?:我想喝|我想要|帮我找|帮我选|有没有|给我来|来一杯|想喝|想要|来点|一些|一点的|一点|什么|比较|好喝的|好喝|推荐|一杯|一份|呢|吗)/g,' ').replace(/^(?:有|请问|请给我)/,'').replace(/(?:的|呀|吧)$/,''));
 const bits=simplified.split(/\s+/).filter(x=>x&&x!=='的'&&x!=='我'&&x!=='想');
 if(!bits.length)return false;
 if(/无酒精|不含酒精|无醇/.test(raw)&&p.alcohol!=='non_alcoholic')return false;
 return bits.every(x=>{
   if(/^(?:无酒精|不含酒精|无醇)$/.test(x))return p.alcohol==='non_alcoholic';
   if(x==='小吃')return p.category==='佐酒与分享'||hay.includes('小吃');
   if(x==='鸡尾酒')return p.alcohol==='alcoholic'||hay.includes(x);
   return hay.includes(x);
 });
}
function searchRank(p,query){
 const q=normalize(query);if(!q)return 0;
 if(normalize(p.name)===q||normalize(p.name_en)===q)return 0;
 if(normalize(p.name).includes(q)||normalize(p.name_en).includes(q))return 1;
 if(normalize([p.category,p.series].join(' ')).includes(q))return 2;
 if(normalize([p.flavor,p.flavor_tag].join(' ')).includes(q))return 3;
 return 4;
}
const flavorTokens={'清爽':['清爽','气泡','干净','明快','清凉','清冽'],'果香':['果香','水果','莓','柑橘','苹果','橙','蜜桃','葡萄'],'酸爽':['酸爽','酸味','微酸','酸甜','青柠','柠檬'],'甜润':['柔滑','甜润','甘甜','奶香','香甜','顺滑'],'浓郁':['浓郁','浓厚','烟熏','烈酒','木质','酒感'],'草本':['草本','薄荷','香草','苦味','杜松']};
function flavorMatch(p,t){if(t==='全部')return true;return (flavorTokens[t]||[t]).some(word=>(p.flavor+' '+p.flavor_tag).includes(word))}
function flavorsIn(ps){return ['全部',...Object.keys(flavorTokens).filter(t=>ps.some(p=>flavorMatch(p,t)))]}
/** [MENU_LIST] 顾客酒单：按分类显示商品、套餐与法律声明。 */
function renderMenu(){const searchItems=items().filter(p=>matchesSearch(p,state.search));const sections=state.scope==='all'?categoryList():[state.scope];if(state.search)sections.sort((a,b)=>Math.min(9,...searchItems.filter(p=>p.category===a).map(p=>searchRank(p,state.search)))-Math.min(9,...searchItems.filter(p=>p.category===b).map(p=>searchRank(p,state.search))));let r=`<div class="inner"><div class="notice"><span class="notice-icon" aria-hidden="true">✦</span><span>${tr('notice')}</span></div>${state.catalogFallback?`<div class="notice" role="status"><span>${tr('fallbackNotice')}</span></div>`:''}`;let count=0;
 for(const cat of sections){const list=searchItems.filter(p=>p.category===cat);if(!list.length)continue;const shown=state.scope!=='all'&&state.filter!=='全部'?list.filter(p=>flavorMatch(p,state.filter)):list;if(!shown.length)continue;if(state.search)shown.sort((a,b)=>searchRank(a,state.search)-searchRank(b,state.search));count+=shown.length;
  r+=`<section class="sec"><div class="sechead"><div><h2>${escapeHtml(categoryName(cat))}</h2><div class="secenglish">${state.lang==='zh'?escapeHtml(categoryEn[cat]||'BAR ST. VINCENT'):'BAR ST. VINCENT'}</div></div><span class="sectotal">${shown.length} ${tr('count')}</span></div><div class="goldline"></div>`;
  if(cat==='套餐与分享'&&state.lang==='zh')r+=`<p class="section-note">喜欢的酒与小食，留给一起坐下的人。</p>`;
  if(state.scope!=='all'&&!state.search&&cat!=='套餐与分享')r+=`<div class="flavors">${flavorsIn(list).map(f=>`<button type="button" data-flavor="${escapeHtml(f)}" class="chip ${state.filter===f?'selected':''}" aria-pressed="${state.filter===f}">${escapeHtml(f==='全部'?tr('all'):f)}</button>`).join('')}</div>`;
  r+=shown.map(pCard).join('')+'</section>';
 }
 if(!count)r+=`<div class="empty">${tr('unavailable')}<div><button data-action="clear" type="button">${tr('clear')}</button></div></div>`;
 r+=`<div class="legalfoot"><b>BAR ST. VINCENT</b><div>${tr('legal')}</div><div>${tr('availability')}</div></div></div>`;return r;
}
function score(p){const hay=(p.flavor+' '+p.flavor_tag).toLowerCase();let val=0;for(const token of flavorTokens[state.recommend.taste]||[])if(hay.includes(token))val+=2;
 if(state.recommend.occasion==='慢慢品味'&&/余韵|木香|橡木|悠长|醇厚|层次/.test(hay))val+=2;
 if(state.recommend.occasion==='和朋友聊聊'&&/清爽|气泡|轻盈|果香/.test(hay))val+=2;
 if(state.recommend.occasion==='想来点新鲜的'&&p.category==='本季特调')val+=2;
 return val;
}
function recommendations(){const ps=items().filter(p=>p.kind==='prepared'&&p.selectable&&(state.recommend.alcohol==='all'||(state.recommend.alcohol==='no'?p.alcohol==='non_alcoholic':p.alcohol==='alcoholic')));
 const ranked=ps.map((p,i)=>({p,v:score(p),i})).sort((a,b)=>b.v-a.v||a.i-b.i);
 if(!ranked.length)return [];
 const offset=(state.recRound*4)%ranked.length;return Array.from({length:Math.min(4,ranked.length)},(_,i)=>ranked[(offset+i)%ranked.length].p);
}
/** [TASTE_GUIDE] “帮我选”三组选项与推荐展示；不使用NPS/销量。 */
function renderRecommend(){const opt=(field,val,label)=>`<button type="button" data-rec-field="${field}" data-rec-value="${escapeHtml(val)}" class="answer ${state.recommend[field]===val?'on':''}" aria-pressed="${state.recommend[field]===val}">${escapeHtml(label)}</button>`;
 let r=`<div class="inner"><div class="page-head"><div class="micro">A LITTLE GUIDANCE</div><h1>${tr('recTitle')}</h1><p>${tr('recSub')}</p></div>`;
 r+=`<section class="question"><h3>${tr('q1')}</h3><div class="choices">${opt('alcohol','all',tr('both'))}${opt('alcohol','yes',tr('yes'))}${opt('alcohol','no',tr('no'))}</div></section>`;
 r+=`<section class="question"><h3>${tr('q2')}</h3><div class="choices">${opt('taste','清爽',tr('fresh'))}${opt('taste','果香',tr('fruit'))}${opt('taste','甜润',tr('sweet'))}${opt('taste','浓郁',tr('strong'))}</div></section>`;
 r+=`<section class="question"><h3>${tr('q3')}</h3><div class="choices">${opt('occasion','慢慢品味',tr('relax'))}${opt('occasion','和朋友聊聊',tr('social'))}${opt('occasion','想来点新鲜的',tr('exploreTaste'))}</div></section>`;
 r+=`<section class="recommend-results" aria-live="polite"><div class="sechead"><div><h2>${tr('recResults')}</h2><div class="secenglish">A TASTE OF DISCOVERY</div></div></div><div class="goldline"></div>`;
 if(state.recLoading)r+=`<div class="rec-progress" role="status" aria-live="polite"><div class="rec-ritual" aria-hidden="true"><span class="rec-ring rec-ring-outer"></span><span class="rec-ring rec-ring-inner"></span><div class="rec-ritual-core"><img src="./assets/bsv-mark.webp" width="88" height="88" alt=""></div><span class="rec-ritual-star rec-ritual-star-a">✧</span><span class="rec-ritual-star rec-ritual-star-b">✧</span></div><p>${tr('recLoading')}</p><div class="rec-progress-track" aria-hidden="true"><span></span></div><div class="rec-small">BAR ST. VINCENT</div></div>`;
 else r+=`<div class="rec-reveal"><p class="reco-note">${tr('recCaution')}</p>${recommendations().map(pCard).join('')||`<div class="empty">${tr('unavailable')}</div>`}<button type="button" class="refresh-reco" data-action="refreshRec"><span aria-hidden="true">↻</span> ${tr('recRefresh')}</button></div>`;
 r+=`</section><div class="legalfoot">${tr('legal')}</div></div>`;return r;
}
let recommendTimer=null;let recommendVersion=0;
/** [RECOMMEND_MOTION] 1.5秒Logo过渡；只用于视觉仪式，不代表AI推理速度。 */
function beginRecommendation({fresh=false,resetScroll=false}={}){
 if(fresh)state.recRound=0;
 clearTimeout(recommendTimer);const version=++recommendVersion;state.recLoading=true;renderContent(resetScroll);
 recommendTimer=setTimeout(()=>{if(version!==recommendVersion||state.page!=='recommend')return;state.recLoading=false;state.recShown=true;renderContent(false)},bsvReducedMotion.matches?0:1500);
}
const bsvReducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
let bsvScrollRAF=0;
function scheduleScrollBrand(){
 if(bsvScrollRAF)return;
 bsvScrollRAF=window.requestAnimationFrame(()=>{
  bsvScrollRAF=0;const sc=$('content');if(!sc)return;
  const max=Math.max(0,sc.scrollHeight-sc.clientHeight),fraction=max?Math.min(1,sc.scrollTop/max):0;
  const shell=$('shell');
  shell.style.setProperty('--scroll-progress',fraction.toFixed(4));
  if(bsvReducedMotion.matches){shell.style.setProperty('--scroll-turn','0deg');shell.style.setProperty('--auraY','0px');shell.style.setProperty('--ambient-turn','0deg');return;}
  const distance=sc.scrollTop;
  shell.style.setProperty('--scroll-turn',(distance*.23).toFixed(2)+'deg');
  shell.style.setProperty('--ambient-turn',(distance*.018).toFixed(2)+'deg');
  shell.style.setProperty('--auraY',Math.min(35,distance*.025).toFixed(1)+'px');
 });
}
/**
 * [VIEW_RENDER] 唯一的主体内容渲染入口。仅改变商品展示，不修改数据库。
 * scrollTop=true 表示切分类时回到当前商品区域顶部；false 保持阅读位置。
 */
function renderContent(scrollTop=false){
 if(!state.data)return;
 const sc=$('content').scrollTop;
 $('content').innerHTML=state.page==='recommend'?renderRecommend():renderMenu();
 $('content').scrollTop=scrollTop?0:sc;
 $('menuBtn').classList.toggle('active',state.page==='menu');
 $('guideBtn').classList.toggle('active',state.page==='recommend');
 $('categories').hidden=state.page==='recommend';
 scheduleScrollBrand();
}

/**
 * [MOTION_V11_NO_GHOST] 商品分类切换——只绘制新内容，不保留旧内容快照。
 * 根因：startViewTransition 会同时绘制旧页面截图和新的文字，导致双重文字/残影。
 * 修复：同步更新唯一 DOM，然后只为新列表施加轻柔透明度过渡；不位移文字。
 * 连续点击立即取消先前动画。没有 Web Animations API 时仍可正常切换。
 * 不影响搜索输入、不改变价格、不改变数据库。具体时长见 style.css。
 */
let activeMenuEntry=null;
function transitionMenu(change){
 if(activeMenuEntry){activeMenuEntry.cancel();activeMenuEntry=null;}
 change(); // Immediately commit new content; there is never a second copy of the old text.
 if(bsvReducedMotion.matches || state.modal || !state.data)return;
 const inner=$('content').querySelector('.inner');
 if(!inner || typeof inner.animate!=='function')return;
 const timing=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bsv-menu-enter'))||170;
 const a=inner.animate([{opacity:.58},{opacity:1}],{duration:timing,easing:'cubic-bezier(.2,.75,.25,1)',fill:'none'});
 activeMenuEntry=a;
 a.finished.catch(()=>{}).finally(()=>{if(activeMenuEntry===a)activeMenuEntry=null;});
}
function refreshI18n(){document.documentElement.lang=state.lang==='zh'?'zh-CN':'en';document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=tr(el.dataset.i18n));$('search').placeholder=tr('search');$('store').options[0].textContent=tr('store');$('lang').textContent=state.lang==='zh'?'EN':'中';$('cartTrigger').setAttribute('aria-label',tr('cart'));$('searchBtn').setAttribute('aria-label',tr('searchBubbleLabel'));$('searchBubble').placeholder=tr('searchBubble');$('searchBubble').setAttribute('aria-label',tr('searchBubbleLabel'));$('searchPopover').setAttribute('aria-label',tr('searchBubbleLabel'));$('searchBubbleClose').setAttribute('aria-label',tr('searchClose'));$('searchBubbleClear').setAttribute('aria-label',tr('searchClear'))}
function cartCount(){return Object.values(state.cart).reduce((sum,qty)=>sum+qty,0)}
function cartBadge(){const n=cartCount();$('cartCount').hidden=!n;$('cartCount').textContent=n>99?'99+':String(n)}
function saveSelection(){try{sessionStorage.setItem('bsvSelectionMenuV8',JSON.stringify({cart:state.cart,store:state.cartStore}))}catch(e){}cartBadge()}
function restoreSelection(){try{const saved=JSON.parse(sessionStorage.getItem('bsvSelectionMenuV8')||'{}');if(saved&&typeof saved.cart==='object')state.cart=Object.fromEntries(Object.entries(saved.cart).filter(([id,qty])=>Number.isInteger(qty)&&qty>0&&qty<=30&&findProduct(id)?.selectable));state.cartStore=typeof saved.store==='string'?saved.store:''}catch(e){}cartBadge()}
let priorFocus=null;
function modalWrap(title,eyebrow,body,footer){return `<div class="layer" id="modalLayer" role="presentation"><section class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title"><div class="sheet-handle" aria-hidden="true"></div><div class="sheethead"><div><div class="eyebrow">${escapeHtml(eyebrow)}</div><h2 id="sheet-title" tabindex="-1">${escapeHtml(title)}</h2></div><button class="close" type="button" data-action="close" aria-label="${state.lang==='zh'?'关闭':'Close'}">×</button></div><div class="sheetbody">${body}</div><div class="sheetfoot">${footer}</div></section></div>`}
function openModal(kind,id){closeSearchBubble();$('toast').hidden=true;priorFocus=document.activeElement;state.modal=kind;state.detail=id||null;renderModal();$('modalHost').querySelector('#sheet-title')?.focus();$('shell').inert=true;document.body.style.overflow='hidden'}
function closeModal(){state.modal=null;state.detail=null;$('modalHost').innerHTML='';$('shell').inert=false;document.body.style.overflow='';if(priorFocus?.isConnected)priorFocus.focus();priorFocus=null}
function parseBundleText(s){
 const parts={contents:'',choices:'',summary:'',notes:''};if(!s)return parts;
 const keys={"套餐内容":"contents","包含内容":"contents","可选":"choices","商品简介":"summary","商品介绍":"summary","使用说明":"notes","购买须知":"notes"};
 const lines=String(s).replace(/\r/g,'').split('\n');let section=null;
 for(const raw of lines){const trimmed=raw.trim();if(!trimmed)continue;
  if(trimmed==='商品标题'||trimmed==='商品名称') {section='skip';continue;}
  let found=false;
  for(const [name,field] of Object.entries(keys))if(trimmed===name||trimmed===name+'：'||trimmed.startsWith(name+'：')){
   section=field;const remainder=trimmed.slice(name.length).replace(/^：/,'').trim();if(remainder)parts[field]+=(parts[field]?'\n':'')+remainder;found=true;break;
  }
  if(found||section==='skip')continue;
  if(section)parts[section]+=(parts[section]?'\n':'')+trimmed;
  else parts.summary+=(parts.summary?'\n':'')+trimmed;
 }
 return parts;
}
function guestBundleLine(s){return String(s||'').replace(/\bSKU\b/gi,'酒款').replace(/同批次出品/g,'').replace(/\bNPS\b/gi,'').replace(/按门店本批次无限瓶出品/g,'按门店当天提供的酒款出品').replace(/\n{3,}/g,'\n\n').trim()}
function detailImage(p){if(p.photo&&/^\.?\/?(?:assets|images)\/[a-zA-Z0-9_./-]+$/.test(p.photo))return `<img src="${escapeHtml(p.photo)}" alt="${escapeHtml(guestName(p))}" loading="lazy">`;
 return `<span class="detail-monogram" aria-hidden="true"></span><span class="detail-brand" aria-hidden="true">BAR ST. VINCENT</span>`;}
/** [DETAIL] 商品详情弹窗：公开信息，无制作配方和内部成本。 */
function renderDetail(){const p=findProduct(state.detail);if(!p)return '';const tags=[p.category,p.kind==='bundle'?(p.active?'':''):p.alcohol==='alcoholic'?tr('alcohol'):p.alcohol==='non_alcoholic'?tr('noAlcohol'):'',labelOf(p)].filter(Boolean);
 let body=`${p.name_en?`<div class="detail-en">${escapeHtml(p.name_en)}</div>`:''}<div class="detail-image">${detailImage(p)}</div><div class="detail-tags">${tags.map(x=>`<span class="detail-tag">${escapeHtml(categoryName(x))}</span>`).join('')}</div><section class="detail-section lead-price">${priceDetails(p)}</section>`;
 if(p.kind==='bundle'){
  const sections=parseBundleText(p.description);const summary=guestBundleLine(sections.summary||(!/上架前|待核|内部|锁定/.test(p.contents||'')?p.contents:''));
  if(summary)body+=`<section class="detail-section"><h3>${tr('story')}</h3><p>${escapeHtml(summary)}</p></section>`;
  for(const [label,val] of [[tr('ingredients'),sections.contents||(!/上架前|待核|内部|锁定/.test(p.contents||'')?p.contents:'')],[tr('choices'),sections.choices],...[ [tr('notes'),sections.notes] ]])if(val)body+=`<section class="detail-section"><h3>${label}</h3><p>${escapeHtml(guestBundleLine(val))}</p></section>`;
 }else{
  body+=`<section class="detail-section"><h3>${tr('flavor')}</h3><p>${escapeHtml(flavorCopy(p))}</p></section>`;
  const story=safeStory(p);if(story&&state.lang==='zh')body+=`<section class="detail-section"><h3>${tr('story')}</h3><p>${escapeHtml(story)}</p></section>`;
 }
 body+=`<p class="subtle-footnote">${tr('availability')}</p>`;
 const footer=eligible(p)?`<button type="button" class="primary-btn" data-action="add" data-id="${escapeHtml(p.product_id)}">${tr('add')}</button><div class="sheet-hint">${tr('detailNote')}</div>`:
  `<div class="coming-note">${tr(p.kind==='bundle'?'previewOnly':'productAsk')}</div><button type="button" class="secondary-btn" data-action="close">${tr('continue')}</button>`;
 return modalWrap(guestName(p),p.kind==='bundle'?'BAR ST. VINCENT · SHARING':'BAR ST. VINCENT · THE MENU',body,footer);
}
function cartRows(receipt=false){return Object.entries(state.cart).map(([id,qty])=>{const p=findProduct(id);if(!p)return '';const data=priceInfo(p);return `<div class="cart-line"><div class="cartcopy"><strong>${escapeHtml(guestName(p))}</strong><small>${escapeHtml(data.primary)}${data.value!==null?` / ${escapeHtml(data.secondary)}`:''}</small></div>${receipt?`<strong>× ${qty}</strong>`:`<div class="qty"><button type="button" data-qty="${escapeHtml(id)}" data-step="-1" aria-label="减少 ${escapeHtml(p.name)}">−</button><strong>${qty}</strong><button type="button" data-qty="${escapeHtml(id)}" data-step="1" aria-label="增加 ${escapeHtml(p.name)}">+</button></div>`}</div>`}).join('')}
/** [CART_KNOWN_SUBTOTAL] 有未标价商品时仍显示其他已标价商品的小计，不能虚构未标价金额。 */
function cartTotals(){let total=0,unpriced=0,priced=0;
 for(const [id,qty] of Object.entries(state.cart)){
  const p=findProduct(id);if(!p)continue;
  const x=priceInfo(p);if(x.value===null)unpriced+=qty;else{total+=x.value*qty;priced+=qty;}
 }
 return {total,unpriced,priced};
}
/** [SELECTION] 选酒单与请调酒师确认的页面；不创建支付订单。 */
function renderCart(receipt=false){const count=cartCount(),changed=state.cartStore!==state.store&&count>0;let body=`<div class="basket-note">${receipt?tr('receiptInstruction'):tr('cartNote')}<div class="store-in-cart">${escapeHtml(storeName())}</div></div>`;
 if(changed)body+=`<div class="basket-note" role="status">${tr('storeChange')}</div>`;
 if(receipt)body+=`<div class="receipt-heading">${tr('selectionHeading')}</div>`;
 body+=count?cartRows(receipt):`<div class="empty">${tr('emptyCart')}</div>`;
 const total=cartTotals();if(total.priced)body+=`<div class="cart-total"><span>${tr('approxTotal')}</span><strong>${yuan(total.total)}</strong></div>`;
 if(total.unpriced)body+=`<p class="fine-print">${tr('unpricedCart').replace('{n}',String(total.unpriced))}</p>`;
 if(count)body+=`<p class="fine-print">${tr('totalNote')}</p>`;
 if(receipt)body+=`<div class="basket-note">${tr('atCounter')}<p>${tr('detailNote')}</p></div>`;
 let footer='';if(changed&&!receipt)footer+=`<button class="secondary-btn" data-action="reconcile" type="button">${tr('checkStore')}</button>`;
 if(receipt)footer+=`<button class="primary-btn" data-action="editCart" type="button">${tr('back')}</button>`;
 else if(count&&!changed)footer+=`<button class="primary-btn" data-action="receipt" type="button">${tr('receipt')}</button>`;
 footer+=`<button class="secondary-btn" data-action="close" type="button">${tr('continue')}</button>`;
 return modalWrap(receipt?tr('receipt'):tr('cart'),receipt?'BAR ST. VINCENT':'YOUR SELECTION',body,footer);
}
function renderModal(){if(!state.modal)return;$('modalHost').innerHTML=state.modal==='detail'?renderDetail():renderCart(state.modal==='receipt')}
let toastTimer=null;function notify(msg){$('toast').textContent=msg;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,2500)}
let searchBubbleOpen=false,searchFocusTimer=0;
function syncSearchFields(value){
  $('search').value=value;$('searchBubble').value=value;
  $('searchBubbleClear').hidden=!value.trim();
}
/** [SEARCH] 顶部/底部气泡共享即时关键词搜索；此处不增加延迟。 */
function filterFromSearch(value){
  state.search=value;state.scope='all';state.filter='全部';state.page='menu';
  syncSearchFields(value);renderCats();renderContent(true);
}
/** [SEARCH_BUBBLE] 底部中央搜索键打开细长气泡。 */
function openSearchBubble(){
  if(state.modal)return;
  if(state.page!=='menu'){state.page='menu';state.scope='all';state.filter='全部';renderCats();renderContent(true)}
  searchBubbleOpen=true;
  const bubble=$('searchPopover');bubble.inert=false;bubble.setAttribute('aria-hidden','false');
  bubble.classList.add('open');$('searchBtn').setAttribute('aria-expanded','true');
  syncSearchFields(state.search);updateKeyboardLift();
  clearTimeout(searchFocusTimer);
  // Let the capsule begin appearing before the keyboard changes the viewport.
  searchFocusTimer=setTimeout(()=>{if(searchBubbleOpen&&!state.modal)$('searchBubble').focus({preventScroll:true})},window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:80);
}
function closeSearchBubble({restoreFocus=false}={}){
  if(!searchBubbleOpen)return;
  searchBubbleOpen=false;clearTimeout(searchFocusTimer);
  const bubble=$('searchPopover');bubble.classList.remove('open');bubble.inert=true;bubble.setAttribute('aria-hidden','true');
  $('searchBtn').setAttribute('aria-expanded','false');
  updateKeyboardLift();if(restoreFocus)$('searchBtn').focus({preventScroll:true});
  else if(document.activeElement===$('searchBubble'))$('searchBubble').blur();
}
/**
 * [V12_VISUAL_VIEWPORT] iOS/微信/Android 软键盘视口同步。
 * 正常状态保持 CSS 100dvh：浏览器工具栏改变时顶部与底栏自动贴合屏幕。
 * 部分 iOS Safari 的软键盘只缩小 VisualViewport 而不缩小 CSS 100dvh，
 * 此时仅在输入框聚焦期间把整个 #shell 调成可视高度，让底栏留在键盘上方。
 * 禁止再对搜索气泡增加 keyboard-lift：整个容器已经移动，叠加会抬高两次。
 * 不设置 window.scrollTop，不阻止中间列表的惯性滚动。
 */
function updateKeyboardLift(){
 const shell=$('shell');if(!shell)return;
 const vv=window.visualViewport;
 const focused=document.activeElement;
 const typing=!!focused&&(focused.tagName==='TEXTAREA'||(focused.tagName==='INPUT'&&!['checkbox','radio','button','hidden'].includes(focused.type)));
 const covered=vv?Math.max(0,window.innerHeight-(vv.height+vv.offsetTop)):0;
 const keyboard=!!vv&&typing&&vv.scale<1.1&&covered>120;
 shell.style.setProperty('--bsv-app-height',keyboard?Math.max(260,Math.round(vv.height))+'px':'100dvh');
 shell.style.setProperty('--keyboard-lift','0px');
 shell.dataset.keyboard=keyboard?'open':'closed';
}
/** [ACTION_CATEGORY] 顶部“环球精选 / 套餐与分享 / 经典调酒...”切换 */
function setScope(cat){
 closeSearchBubble();
 if(state.page==='menu' && state.scope===cat && !state.search && state.filter==='全部')return;
 // 键盘用户按 Enter/空格选分类后，将焦点交还新生成的同一按钮。
 const keepKeyboardFocus=$('categories').contains(document.activeElement) && document.activeElement.matches(':focus-visible');
 transitionMenu(()=>{
  state.page='menu';state.scope=cat;state.search='';state.filter='全部';
  syncSearchFields('');renderCats();renderContent(true);
  if(keepKeyboardFocus){
   const selected=Array.from($('categories').querySelectorAll('[data-category]')).find(el=>el.dataset.category===cat);
   selected?.focus({preventScroll:true});
  }
 });
}
/** [ACTION_STORE] 门店切换：仅改变到店身份；C/K标价各店一致。 */
function setStore(id){
 closeSearchBubble();
 transitionMenu(()=>{
  const valid=state.data.stores.some(s=>s.store_id===id&&s.menu_type==='cocktail');
  state.store=valid?id:'';$('store').value=state.store;
  try{sessionStorage.setItem('bsvCustomerBarV8',state.store)}catch(e){}
  renderContent(false);if(state.modal)renderModal();
 });
}
function setTheme(theme){state.theme=theme;document.documentElement.dataset.theme=theme;try{localStorage.setItem('bsvCustomerThemeV8',theme)}catch(e){}}
function initEvents(){
 $('lang').addEventListener('click',()=>{closeSearchBubble();transitionMenu(()=>{state.lang=state.lang==='zh'?'en':'zh';refreshI18n();renderCats();renderContent(false);if(state.modal)renderModal()})});
 $('theme').addEventListener('click',()=>setTheme(state.theme==='dark'?'light':'dark'));
 $('store').addEventListener('change',e=>setStore(e.target.value));
 const updateSearch=e=>{if(e.isComposing)return;filterFromSearch(e.target.value)};
 $('search').addEventListener('input',updateSearch);$('search').addEventListener('compositionend',updateSearch);
 $('searchBubble').addEventListener('input',updateSearch);$('searchBubble').addEventListener('compositionend',updateSearch);
 $('searchBubbleClose').addEventListener('click',()=>closeSearchBubble({restoreFocus:true}));
 $('searchBubbleClear').addEventListener('click',()=>{filterFromSearch('');$('searchBubble').focus({preventScroll:true})});
 $('searchBubble').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();closeSearchBubble({restoreFocus:true});$('content').focus({preventScroll:true})}});
 $('search').addEventListener('focus',()=>closeSearchBubble());
 document.addEventListener('pointerdown',e=>{if(!searchBubbleOpen)return;if(e.target.closest('#searchPopover,#searchBtn'))return;closeSearchBubble()},{passive:true});
 // [V12_VIEWPORT_EVENTS] 监听视觉视口与焦点变化，不监听内容滚动造成的尺寸抖动。
 if(window.visualViewport){window.visualViewport.addEventListener('resize',updateKeyboardLift,{passive:true});window.visualViewport.addEventListener('scroll',updateKeyboardLift,{passive:true})}
 window.addEventListener('resize',updateKeyboardLift,{passive:true});
 document.addEventListener('focusin',()=>setTimeout(updateKeyboardLift,70));
 document.addEventListener('focusout',()=>setTimeout(updateKeyboardLift,100));
 updateKeyboardLift();

 $('menuBtn').addEventListener('click',()=>{closeSearchBubble();transitionMenu(()=>{state.page='menu';renderCats();renderContent(true)})});
 $('guideBtn').addEventListener('click',()=>{closeSearchBubble();state.page='recommend';beginRecommendation({fresh:!state.recShown,resetScroll:true})});
 $('searchBtn').addEventListener('click',()=>{if(searchBubbleOpen)closeSearchBubble({restoreFocus:true});else openSearchBubble()});
 $('cartTrigger').addEventListener('click',()=>openModal('cart'));
 $('categories').addEventListener('click',e=>{const b=e.target.closest('[data-category]');if(b)setScope(b.dataset.category)});
 $('content').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  if(b.dataset.product){openModal('detail',b.dataset.product);return}
  if(b.dataset.flavor){if(state.filter!==b.dataset.flavor)transitionMenu(()=>{state.filter=b.dataset.flavor;renderContent(false)});return}
  if(b.dataset.recField){if(state.recommend[b.dataset.recField]===b.dataset.recValue)return;state.recommend[b.dataset.recField]=b.dataset.recValue;beginRecommendation();return}
  if(b.dataset.action==='refreshRec'){state.recRound++;beginRecommendation();return}
  if(b.dataset.action==='clear'){transitionMenu(()=>{state.scope='all';state.search='';state.filter='全部';syncSearchFields('');renderCats();renderContent(true)})}
 });
 $('modalHost').addEventListener('click',e=>{if(e.target.id==='modalLayer'){closeModal();return}const b=e.target.closest('button');if(!b)return;
  if(b.dataset.action==='close'){closeModal();return}
  if(b.dataset.action==='add'){const p=findProduct(b.dataset.id);if(p&&eligible(p)){if(!cartCount())state.cartStore=state.store;state.cart[p.product_id]=Math.min(30,(state.cart[p.product_id]||0)+1);saveSelection();closeModal();notify(state.lang==='zh'?'已经放进您的选酒单':'Added to your selection')}return}
  if(b.dataset.step){const id=b.dataset.qty,q=Number(b.dataset.step);if(id in state.cart&&Math.abs(q)===1){const next=Math.min(30,state.cart[id]+q);if(next<=0)delete state.cart[id];else state.cart[id]=next;saveSelection();renderModal()}return}
  if(b.dataset.action==='receipt'){state.modal='receipt';renderModal();$('sheet-title')?.focus();return}
  if(b.dataset.action==='editCart'){state.modal='cart';renderModal();$('sheet-title')?.focus();return}
  if(b.dataset.action==='reconcile'){state.cartStore=state.store;saveSelection();renderModal()}
 });
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&searchBubbleOpen){e.preventDefault();closeSearchBubble({restoreFocus:true});return}if(!state.modal)return;if(e.key==='Escape'){closeModal();return}
  if(e.key==='Tab'){const els=Array.from($('modalHost').querySelectorAll('button:not([disabled]),[tabindex="0"],input,select')).filter(x=>x.getClientRects().length);if(!els.length)return;const first=els[0],last=els.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
 });
 $('content').addEventListener('scroll',scheduleScrollBrand,{passive:true});scheduleScrollBrand();
}
/** [CATALOG_VALIDATE] 公共API商品身份与格式校验，防止异常数据覆盖顾客界面。 */
function validateCatalog(data){
 if(!data||typeof data!=='object'||Array.isArray(data)||data.schema!=='bsv.public-menu.v2'||data.currency!=='CNY'||!Array.isArray(data.items)||!Array.isArray(data.stores))throw new Error('Invalid catalogue format');
 if(data.items.length>2000||data.stores.length>200)throw new Error('Catalogue size exceeded');
 const top=new Set(['schema','source','generated_at','stores','items','currency','note','catalog_version']);
 if(Object.keys(data).some(k=>!top.has(k)))throw new Error('Unexpected catalogue field');
 for(const k of ['source','generated_at','note','catalog_version'])if(k in data&&typeof data[k]!=='string')throw new Error('Invalid catalogue metadata');
 const allowedItem=new Set(['product_id','sku','kind','name','name_en','category','family','series','flavor','flavor_tag','story','alcohol','reference_price','reference_prices','price_by_store','public_flavor','status','active','selectable','contents','description','store_variant','photo']);
 const ids=new Set(),skus=new Set(),stores=new Set();
 for(const p of data.items){
  if(!p||typeof p!=='object'||Array.isArray(p)||typeof p.product_id!=='string'||!/^[CK]\d{6,}$/.test(p.product_id)||ids.has(p.product_id))throw new Error('Duplicate item identity');
  if(p.kind!=='prepared'&&p.kind!=='bundle')throw new Error('Unsupported product type');
  if((p.kind==='prepared'&&!p.product_id.startsWith('C'))||(p.kind==='bundle'&&!p.product_id.startsWith('K')))throw new Error('Product domain mismatch');
  if(Object.keys(p).some(k=>!allowedItem.has(k)))throw new Error('Private or unsupported item property');
  for(const key of ['name','category'])if(typeof p[key]!=='string'||!p[key].trim()||p[key].length>400)throw new Error('Invalid public product field');
  for(const k of ['name_en','family','series','flavor','flavor_tag','story','contents','description','store_variant','photo','public_flavor','sku'])if(k in p&&p[k]!==null&&typeof p[k]!=='string')throw new Error('Invalid public text');
  for(const k of ['alcohol','status'])if(k in p&&typeof p[k]!=='string')throw new Error('Invalid public status');
  for(const k of ['active','selectable'])if(k in p&&typeof p[k]!=='boolean')throw new Error('Invalid public flag');
  if('reference_prices' in p&&p.reference_prices!==null)throw new Error('Unexpected auxiliary prices');
  if(!Object.hasOwn(p,'reference_price'))throw new Error('Missing reference price');
  if(p.reference_price!==null){
   const price=p.reference_price;
   if(!price||typeof price!=='object'||Array.isArray(price)||typeof price.label!=='string'||Object.keys(price).some(k=>k!=='amount'&&k!=='label'))throw new Error('Unexpected reference price field');
   const n=p.reference_price?.amount;
   if(typeof n!=='number'||!Number.isFinite(n)||n<0||n>=1000000)throw new Error('Invalid reference price');
  }
  if('price_by_store' in p&&(!p.price_by_store||typeof p.price_by_store!=='object'||Array.isArray(p.price_by_store)||Object.keys(p.price_by_store).length))throw new Error('Store prices not approved for this contract');
  ids.add(p.product_id);
  if(p.sku){if(typeof p.sku!=='string'||!/^[CK][A-Z]{4}\d{5}$/.test(p.sku)||skus.has(p.sku))throw new Error('Invalid item code');skus.add(p.sku)}
 }
 for(const s of data.stores){
  if(!s||typeof s!=='object'||Array.isArray(s)||Object.keys(s).some(k=>!['store_id','name','menu_type'].includes(k))||typeof s.store_id!=='string'||!/^[A-Z0-9]{4,12}$/.test(s.store_id)||stores.has(s.store_id)||typeof s.name!=='string'||!['cocktail','craft'].includes(s.menu_type))throw new Error('Invalid store record');
  stores.add(s.store_id);
 }
 return true;
}
async function readPublishedCatalog(url){
 const controller=new AbortController();
 const raw=Number(cfg.catalogTimeoutMs);const timeoutMs=Number.isFinite(raw)?Math.min(15000,Math.max(1000,raw)):6000;
 const timer=setTimeout(()=>controller.abort(),timeoutMs);
 try{
  const response=await fetch(url,{cache:'no-store',credentials:'omit',redirect:'error',headers:{'Accept':'application/json'},signal:controller.signal});
  if(!response.ok)throw new Error('Catalogue HTTP '+response.status);
  const body=await response.text();
  if(body.length>1500000)throw new Error('Catalogue too large');
  const data=JSON.parse(body);validateCatalog(data);return data;
 }finally{clearTimeout(timer)}
}
async function resolvePublishedCatalog(){
 if(window.BSV_EMBEDDED_CATALOG){validateCatalog(window.BSV_EMBEDDED_CATALOG);return window.BSV_EMBEDDED_CATALOG;}
 const main=cfg.catalogUrl||'./data/menu-public.json';
 try{state.catalogFallback=false;return await readPublishedCatalog(main)}
 catch(err){
  const backup=cfg.fallbackCatalogUrl;
  if(!backup||new URL(backup,location.href).href===new URL(main,location.href).href)throw err;
  // Fallback is a published public snapshot, NOT a second writable database or a payment authority.
  const parsed=new URL(backup,location.href);
  if(parsed.origin!==location.origin||parsed.protocol!==location.protocol)throw new Error('Fallback must be same-origin');
  console.warn('BSV public menu primary unavailable: using approved snapshot',err);
  const data=await readPublishedCatalog(backup);state.catalogFallback=true;return data;
 }
}
/** [CATALOG_READ] 唯一公开数据接口，从 menu-config.js 的 catalogUrl 读取。 */
async function loadCatalogue(){
 try{
  const data=await resolvePublishedCatalog();state.data=data;
  let saved='';try{saved=sessionStorage.getItem('bsvCustomerBarV8')||''}catch(e){}
  const param=new URLSearchParams(location.search).get('store');const preferred=(param||saved||cfg.defaultStoreId||'').toUpperCase();const bars=data.stores.filter(s=>s.menu_type==='cocktail');
  $('store').innerHTML=`<option value="">${tr('store')}</option>`+bars.map(s=>`<option value="${escapeHtml(s.store_id)}">${escapeHtml(s.name)}</option>`).join('');
  state.store=bars.some(s=>s.store_id===preferred)?preferred:'';$('store').value=state.store;
  try{const chosen=localStorage.getItem('bsvCustomerThemeV8');setTheme(['light','dark'].includes(chosen)?chosen:(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'))}catch(e){}
  restoreSelection();refreshI18n();renderCats();renderContent();if(!loadCatalogue.initialized){initEvents();loadCatalogue.initialized=true}
  // Only products + quantities; prices must always be calculated on the trusted staff server.
  if(!window.BSVMenuBridge)Object.defineProperty(window,'BSVMenuBridge',{configurable:false,writable:false,value:Object.freeze({getSelection:()=>({schema:'bsv.menu-intent.v1',store_id:state.store||null,lines:Object.entries(state.cart).map(([id,quantity])=>({product_id:id,sku:findProduct(id)?.sku||null,quantity})),submitted:false,price_must_be_calculated_server_side:true})})});
 }catch(err){console.error('Unable to load public catalogue',err);$('content').innerHTML=`<div class="inner"><div class="page-head"><h1>${tr('loadError')}</h1><button type="button" class="refresh-reco" id="retryCatalog">${tr('retry')}</button></div></div>`;$('retryCatalog')?.addEventListener('click',loadCatalogue)}
}
loadCatalogue();
