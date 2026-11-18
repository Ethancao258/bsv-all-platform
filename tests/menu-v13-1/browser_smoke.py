from pathlib import Path
import re,sys,json
from playwright.sync_api import sync_playwright
root=(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else (Path(__file__).resolve().parents[2] / 'apps/guest-web/bsv1')/'site')
html=(root/'cocktail/index.html').read_text()
html=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', '',html)
html=re.sub(r'<script\s+[^>]*src="[^"]+"[^>]*></script>','',html)
html=re.sub(r'<link\s+[^>]*>','',html)
style=(root/'cocktail/assets/style.css').read_text()
config=(root/'cocktail/assets/menu-config.js').read_text()
copy=(root/'cocktail/assets/menu-copy.js').read_text()
app=(root/'cocktail/assets/app.js').read_text()
data=json.loads((root/'cocktail/data/menu-public.json').read_text())
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None,headless=True,args=['--no-sandbox'])
 for width in [320,390,768]:
  page=b.new_page(viewport={'width':width,'height':812},locale='zh-CN',reduced_motion='reduce')
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.set_content(html)
  page.add_style_tag(content=style)
  page.evaluate('(d)=>{window.BSV_EMBEDDED_CATALOG=d}',data)
  for js in [config,copy,app]:page.add_script_tag(content=js)
  page.locator('[data-product]').first.wait_for(timeout=6000)
  # Immutable-ID keyed editorial text must survive a future product name edit.
  stable=page.evaluate("() => {const p=state.data.items.find(x=>x.product_id==='C000001');const before=flavorCopy(p);p.name='边车更新名';const after=flavorCopy(p);p.name='边车';return before===after}")
  assert stable
  initial=page.locator('[data-product]').count()
  assert initial==84,(width,initial)
  assert page.locator('#store option').count()==4
  assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
  assert page.locator('#categories').is_visible()
  page.locator('[data-product]').first.click()
  assert page.locator('#modalHost [role="dialog"]').count()==1
  page.locator('#modalHost [data-action="add"]').click()
  assert page.locator('#cartCount').inner_text()=='1'
  page.locator('#searchBtn').click()
  page.locator('#searchBubble').fill('莫吉托')
  search=page.locator('[data-product]').count(); assert search>=1
  page.locator('#searchBubbleClose').click()
  page.locator('#lang').click()
  assert page.locator('html').get_attribute('lang')=='en'
  page.locator('#guideBtn').click()
  page.locator('[data-rec-field="taste"]').first.wait_for()
  assert errors==[],errors
  results.append({'width':width,'initial':initial,'search_results':search,'no_horizontal_scroll':True,'cart_and_modal':True,'locale_en':True,'recommend':True,'page_errors':errors})
  page.close()
 b.close()
print(json.dumps(results,ensure_ascii=False,indent=2))
