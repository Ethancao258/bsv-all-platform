/* Node standard library, isolated function tests without browser/remote I/O. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.join(__dirname,'../../apps/guest-web/bsv1');
const publicData=JSON.parse(fs.readFileSync(path.join(root,'site/cocktail/data/menu-public.json'),'utf8'));
const code=fs.readFileSync(path.join(root,'site/cocktail/assets/app.js'),'utf8');
const from=code.indexOf('function validateCatalog(data)');const until=code.indexOf('async function loadCatalogue()',from);
assert(from!==-1&&until>from);
const helpers=code.slice(from,until);
async function run(){
 const calls=[];
 const context={console:{warn:()=>{}},AbortController,URL,setTimeout,clearTimeout,
  state:{catalogFallback:false},cfg:{catalogUrl:'https://menu.bsvm.cn/api/menu',fallbackCatalogUrl:'https://menu.bsvm.cn/cocktail/data/menu-public.json',catalogTimeoutMs:3000},
  location:{href:'https://menu.bsvm.cn/cocktail/',origin:'https://menu.bsvm.cn',protocol:'https:'},
  window:{BSV_EMBEDDED_CATALOG:null},
  fetch:async (url)=>{calls.push(url);if(url.includes('/api/'))return {ok:false,status:503};return {ok:true,status:200,text:async()=>JSON.stringify(publicData)}}
 };
 vm.createContext(context);vm.runInContext(helpers,context);
 assert(context.validateCatalog(publicData)===true);
 assert.throws(()=>context.validateCatalog({...publicData,secret:'private'}));
 assert.throws(()=>context.validateCatalog({...publicData,items:[{...publicData.items[0],cost:12}]}));
 assert.throws(()=>context.validateCatalog({...publicData,items:[publicData.items[0],publicData.items[0]]}));
 const first=publicData.items[0];
 assert.throws(()=>context.validateCatalog({...publicData,stores:[{...publicData.stores[0],employee:'private'}]}));
 assert.throws(()=>context.validateCatalog({...publicData,items:[{...first,reference_price:{amount:88,label:'OK',cost:1}}]}));
 assert.throws(()=>context.validateCatalog({...publicData,items:[{...first,story:{recipe:'private'}}]}));
 assert.throws(()=>context.validateCatalog({...publicData,items:[{...first,reference_prices:{cost:1}}]}));
 const resolved=await context.resolvePublishedCatalog();
 assert.equal(resolved.items.length,84);assert.equal(context.state.catalogFallback,true);assert.equal(calls.length,2);
 context.cfg.fallbackCatalogUrl='https://bad.example.com/mirror.json';
 await assert.rejects(context.resolvePublishedCatalog());
 context.cfg.fallbackCatalogUrl=null;
 await assert.rejects(context.resolvePublishedCatalog());
 context.cfg.fallbackCatalogUrl='./data/menu-public.json';
 context.cfg.catalogTimeoutMs=1000;
 let aborted=false;
 context.fetch=async (url, init)=>{
   assert.equal(init.credentials,'omit');
   assert.equal(init.redirect,'error');
   if(url.includes('/api/'))return new Promise((_,reject)=>init.signal.addEventListener('abort',()=>{
     aborted=true;reject(new Error('timeout'));
   },{once:true}));
   return {ok:true,text:async()=>JSON.stringify(publicData)};
 };
 await context.resolvePublishedCatalog();
 assert.equal(aborted,true);
 assert.equal(context.state.catalogFallback,true);
 context.fetch=async()=>({ok:true,text:async()=>JSON.stringify({...publicData,stores:[{...publicData.stores[0],secret:'private'}]})});
 await assert.rejects(context.resolvePublishedCatalog());
 console.log('PASS: data schema, duplicate ID, private fields, invalid primary -> safe same-origin fallback, cross-origin rejected, no fallback -> fail closed');
}
run().catch(e=>{console.error(e);process.exitCode=1});
