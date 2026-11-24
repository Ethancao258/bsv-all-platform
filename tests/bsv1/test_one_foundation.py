"""Run in the extracted delivery folder: python -m unittest discover -s tests -v"""
import os,sys,tempfile,unittest,copy,json
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"services/api/bsv1"
sys.path.insert(0,str(APP))
TEST_TEMP=tempfile.TemporaryDirectory(prefix='bsv-one-test-')
import app,bsv_one,bsv_layouts

class Foundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch
        for name, value in (("DB_PATH", Path(TEST_TEMP.name) / "one.sqlite3"), ("MODE", "local")):
            override = patch.object(app, name, value)
            override.start()
            cls.addClassCleanup(override.stop)
        app.init_db()
        with app.tx() as db:
            import secrets
            for code,role,pin in [('BSVM-MGR','MANAGER','135790'),('BSVM-DEMO','STAFF','246810')]:
                salt=secrets.token_bytes(16)
                db.execute('INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES(?,?,?,?,?,1)',
                           (app.uid(),code,salt.hex(),app.pin_hash(pin,salt),role))
                sid=db.execute('SELECT id FROM staff WHERE staff_code=?',(code,)).fetchone()[0]
                db.execute('INSERT INTO staff_store_access(staff_id,store_id) VALUES(?,?)',(sid,'BSVM'))
            cls.staff=dict(db.execute("SELECT * FROM staff WHERE staff_code='BSVM-MGR'").fetchone())
            db.execute("INSERT INTO bsv_hq_roles(staff_id,role,granted_at) VALUES(?,'HQ_ADMIN',?)",(cls.staff['id'],bsv_one.now()))
    def test_01_baseline_pricing(self):
        with app.db_read() as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            for sid in ('BSVM','BSVS','BSVT','BSVF'):
                rows=app.catalog_for_store(db,sid)
                self.assertEqual(len([x for x in rows if x['domain']=='C']),63)
                self.assertEqual(sum(x['sale_enabled'] for x in rows if x['domain']=='C'),52)
                self.assertEqual(next(x['price_cents'] for x in rows if x['id']=='C000001'),
                                 next(x['price_cents'] for x in app.catalog_for_store(db,'BSVM') if x['id']=='C000001'))
    def test_01b_single_global_product_identity(self):
        with app.db_read() as db:
            products=list(db.execute("SELECT id,store_id FROM bsv_products WHERE demo_only=0"))
            self.assertEqual(len(products),52)
            self.assertEqual(len({r['id'] for r in products}),52)
            self.assertTrue(all(r['id'].startswith('C') and r['store_id'] is None for r in products))
            self.assertEqual(sum(1 for r in products if ':' in r['id']),0)
            from bsv_collab import recipe
            for sid in ('BSVM','BSVS','BSVT','BSVF'):
                self.assertTrue(app.price_is_current(db,db.execute("SELECT * FROM bsv_products WHERE id='C000001'").fetchone(),sid))
                self.assertEqual(recipe(db,sid,'C000001')['fixed_id'],'C000001')
    def test_02_seeds(self):
        with app.db_read() as db:
            self.assertEqual([(x['store_id'],x['version']) for x in db.execute('SELECT store_id,version FROM bsv_layout_revisions ORDER BY store_id')],
                            [('BSVM',1),('BSVS',1),('BSVT',1)])
            self.assertEqual([db.execute('SELECT COUNT(*) FROM seats WHERE store_id=?',(s,)).fetchone()[0] for s in ('BSVM','BSVS','BSVT')],[13,13,17])
    def test_02b_unapproved_floorplans_and_no_demo_skus(self):
        with app.db_read() as db:
            self.assertEqual([x[0] for x in db.execute("SELECT layout_ready FROM stores WHERE id IN ('BSVM','BSVS','BSVT') ORDER BY id")],[0,0,0])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bsv_products WHERE demo_only=1").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bsv_platform_identity WHERE profile='BSV_ONE_CANONICAL_V1'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bsv_layout_revisions WHERE status='PUBLISHED'").fetchone()[0],0)
    def test_02c_can_publish_store_and_mark_approved(self):
        with app.tx() as db:
            current=bsv_one.current(db,'BSVS')
            draft=bsv_one.draft(db,self.staff,'BSVS',current['layout'],current['version'])
            bsv_one.publish(db,self.staff,'BSVS',draft['revision_id'])
            self.assertEqual(db.execute("SELECT layout_ready FROM stores WHERE id='BSVS'").fetchone()[0],1)
    def test_03_staff_cannot_manage(self):
        with app.db_read() as db:
            st=dict(db.execute("SELECT * FROM staff WHERE staff_code='BSVM-DEMO'").fetchone())
            self.assertFalse(bsv_one.is_hq(db,st))
            with self.assertRaises(bsv_one.ControlError):bsv_one.require_hq(db,st)
    def test_04_new_store_manual(self):
        with app.tx() as db:
            a=bsv_one.create_store(db,self.staff,{'store_id':'BSVX','name':'测试店','district':'北京市','business_type':'鸡尾酒吧','design_max_guests':12})
            self.assertEqual(a['store_id'],'BSVX')
            c=bsv_one.current(db,'BSVX');self.assertEqual(c['version'],0)
            self.assertEqual(c['layout']['seats'],[])
    def test_04b_post_approval_order_uses_canonical_product(self):
        with app.tx() as db:
            session_staff=dict(self.staff,session_store_id='BSVS')
            # Headquarters test account intentionally gets separate BSVS login privilege.
            db.execute('INSERT OR IGNORE INTO staff_store_access(staff_id,store_id) VALUES(?,?)',(self.staff['id'],'BSVS'))
        result=app.handle_action('/api/seats/open',{'seat_id':'BSVS-SEAT-0001'},session_staff)
        self.assertTrue(result['new'])
        visit=result['visit_id']
        add=app.handle_action('/api/drafts/add',{'visit_id':visit,'product_id':'C000001'},session_staff)
        self.assertTrue(add['ok'])
        submit=app.handle_action('/api/orders/submit',{'visit_id':visit,'pay_now':False},session_staff)
        self.assertTrue(submit['ok'])
        with app.db_read() as db:
            r=db.execute('SELECT product_id FROM order_lines WHERE order_id=(SELECT id FROM orders WHERE visit_id=?)',(visit,)).fetchone()
            self.assertEqual(r['product_id'],'C000001')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bsv_products WHERE id=?',('C000001',)).fetchone()[0],1)
        app.handle_action('/api/visits/cancel',{'visit_id':visit},session_staff) if False else None
    def test_05_draft_publish_and_restart_source(self):
        # A store with no JSON/SVG resources can be created and laid out only from UI/API.
        with app.tx() as db:
            cfg=bsv_one.current(db,'BSVX')['layout']
            cfg['seats']=[dict(id='BSVX-SEAT-0001',label='窗1',kind='TABLE',x=25,y=20,order=10,capacity=2,group_id=None,is_secondary=False),
                          dict(id='BSVX-SEAT-0002',label='窗2',kind='TABLE',x=70,y=30,order=20,capacity=2,group_id=None,is_secondary=False)]
            cfg['neighbors']={'BSVX-SEAT-0001':{'left':None,'right':'BSVX-SEAT-0002'},'BSVX-SEAT-0002':{'left':'BSVX-SEAT-0001','right':None}}
            d=bsv_one.draft(db,self.staff,'BSVX',cfg,0);self.assertEqual(bsv_one.current(db,'BSVX')['version'],0)
            r=bsv_one.publish(db,self.staff,'BSVX',d['revision_id']);self.assertEqual(r['version'],1)
            self.assertEqual([x['label'] for x in db.execute("SELECT label FROM seats WHERE store_id='BSVX' ORDER BY display_order")],['窗1','窗2'])
            self.assertEqual(db.execute("SELECT origin FROM bsv_layout_ownership WHERE store_id='BSVX'").fetchone()[0],'HQ_PUBLISHED')
            art=bsv_layouts.art_for_store(db,'BSVX');self.assertIn(b'BSVX',art)
        # Existing seed stores also preserve HQ-published coordinates across init_db.
        with app.tx() as db:
            base=bsv_one.current(db,'BSVM');cfg=copy.deepcopy(base['layout']);cfg['seats'][0]['x']=33.7
            d=bsv_one.draft(db,self.staff,'BSVM',cfg,base['version']);bsv_one.publish(db,self.staff,'BSVM',d['revision_id'])
        app.init_db()
        with app.db_read() as db:
            self.assertEqual(round(bsv_one.current(db,'BSVM')['layout']['seats'][0]['x'],1),33.7)
            self.assertTrue(bsv_one.is_hq(db,self.staff))
    def test_06_revision_conflict(self):
        with app.db_read() as db:cfg=bsv_one.current(db,'BSVX')['layout']
        with app.tx() as db:
            with self.assertRaises(bsv_one.ControlError):bsv_one.draft(db,self.staff,'BSVX',cfg,0)
    def test_07_cannot_publish_open_visit(self):
        with app.tx() as db:
            curr=bsv_one.current(db,'BSVX');d=bsv_one.draft(db,self.staff,'BSVX',curr['layout'],curr['version'])
            # Existing valid seat + active visit blocks all structural releases.
            v='VIS-OPEN-TEST';db.execute("INSERT INTO visits(id,store_id,seat_id,guests,status,created_by,created_at) VALUES(?,?,?,1,'OPEN',?,?)",(v,'BSVX','BSVX-SEAT-0001',self.staff['id'],bsv_one.now()))
            with self.assertRaises(bsv_one.ControlError):bsv_one.publish(db,self.staff,'BSVX',d['revision_id'])
            db.execute('DELETE FROM visits WHERE id=?',(v,))
    def test_08_rollback_is_draft(self):
        with app.tx() as db:
            cur=bsv_one.current(db,'BSVX')
            rev=db.execute("SELECT revision_id FROM bsv_layout_revisions WHERE store_id='BSVX' AND status='PUBLISHED'").fetchone()[0]
            ret=bsv_one.rollback_to(db,self.staff,'BSVX',rev)
            self.assertEqual(db.execute('SELECT status FROM bsv_layout_revisions WHERE revision_id=?',(ret['revision_id'],)).fetchone()[0],'DRAFT')
            self.assertEqual(bsv_one.current(db,'BSVX')['version'],cur['version'])
    def test_09_reject_cross_store_seat(self):
        with app.db_read() as db:c=bsv_one.current(db,'BSVX');cfg=c['layout']
        cfg['seats'][0]['id']='BSVM-SEAT-0002'
        with self.assertRaises(bsv_one.ControlError):bsv_one.clean_layout(None,'BSVX',cfg)
    def test_11_image_upload_publish_preference(self):
        import base64,io
        # dependency-free valid PNG asset generation (Python standard library only)
        import io,struct,zlib
        def chunk(kind, payload):
            return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
        w,h=160,160
        pixels=b''.join(b'\x00'+bytes((x+y*3)%256 for x in range(w*3)) for y in range(h))
        raw=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+
             chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))
        self.assertTrue(len(raw)>1000)
        with app.tx() as db:
            r=bsv_one.upload_image(db,self.staff,'BSVX','image/png',base64.b64encode(raw).decode())
            self.assertEqual(r['mime'],'image/png')
            current=bsv_one.current(db,'BSVX');c=current['layout'];c['background_asset_id']=r['asset_id']
            draft=bsv_one.draft(db,self.staff,'BSVX',c,current['version'])
            mime,before=bsv_one.layout_art(db,'BSVX');self.assertEqual(mime,'image/svg+xml')
            bsv_one.publish(db,self.staff,'BSVX',draft['revision_id'])
            mime,after=bsv_one.layout_art(db,'BSVX');self.assertEqual(mime,'image/png')
            self.assertEqual(after,raw)
    def test_12_http_login_hq_menu_and_access(self):
        import threading,http.client
        srv=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        conn=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=5)
        def req(method,path,obj=None,cookie=None,csrf=None):
            headers={}
            if cookie:headers['Cookie']=cookie
            if csrf:headers['X-BSV-CSRF']=csrf
            body=None
            if obj is not None:body=json.dumps(obj);headers['Content-Type']='application/json'
            conn.request(method,path,body,headers);r=conn.getresponse();b=r.read()
            return r.status,dict(r.getheaders()),b
        try:
            code,heads,body=req('GET','/hq');self.assertEqual(code,401)
            code,heads,body=req('POST','/api/login',{'store_id':'BSVM','confirmed_store_id':'BSVM','staff_code':'BSVM-MGR','pin':'135790'})
            self.assertEqual(code,200,body[:600])
            cookie=heads['Set-Cookie'].split(';',1)[0]
            code,heads,body=req('GET','/api/state',cookie=cookie)
            self.assertEqual(code,200);state=json.loads(body);self.assertTrue(state['staff']['can_manage_hq'])
            csrf=state['csrf']
            code,_,page=req('GET','/hq',cookie=cookie);self.assertEqual(code,200);self.assertIn(b'BSV ONE',page)
            code,_,page=req('GET','/menu',cookie=cookie);self.assertEqual(code,200)
            code,_,body=req('GET','/api/menu-preview?store_id=BSVM',cookie=cookie)
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['priced'],52)
            code,_,body=req('GET','/api/catalog/search?q=%E5%90%88%E6%88%90%E5%95%86%E5%93%81&domain=C')
            self.assertEqual(code,401) # employee authentication is required
            code,_,body=req('GET','/api/v1/catalog/products?q=%E5%90%88%E6%88%90%E5%95%86%E5%93%81&domain=C')
            self.assertEqual(code,401) # versioned contract keeps existing employee authorization
            code,_,body=req('GET','/api/catalog/search?q=%E5%90%88%E6%88%90%E5%95%86%E5%93%81&domain=C',cookie=cookie)
            self.assertEqual(code,200)
            catalog=json.loads(body)
            self.assertEqual(len(catalog['items']),63)
            self.assertEqual(sum(item['sale_enabled'] for item in catalog['items']),52)
            code,_,body=req('GET','/api/v1/catalog/products?q=%E5%90%88%E6%88%90%E5%95%86%E5%93%81&domain=C',cookie=cookie)
            self.assertEqual(code,200)
            versioned=json.loads(body)
            self.assertEqual(versioned['contract_version'],'bsv-data-contracts-v1')
            self.assertEqual(versioned['items'][0]['attributes']['name'],'合成商品 1')
            self.assertEqual(len(versioned['items'][0]['product_id']),7)
            code,_,body=req('GET','/api/catalog/item?id=C000001',cookie=cookie)
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['fields']['完整制作步骤'],'演练步骤')
            code,_,body=req('GET','/api/v1/catalog/products/C000001',cookie=cookie)
            self.assertEqual(code,200)
            product=json.loads(body)
            self.assertEqual(product['attributes']['recipe_steps'],'演练步骤')
            self.assertEqual(product['product_id'],'C000001')
            before=app.db_read()
            with before as db:visits_before=db.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
            code,_,body=req('GET','/api/production/recipe?id=C000001',cookie=cookie)
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['fields']['完整制作步骤'],'演练步骤')
            code,_,body=req('GET','/api/v1/catalog/products/C000001/recipe',cookie=cookie)
            self.assertEqual(code,200)
            self.assertNotIn('sourcing_guide',json.loads(body)['attributes'])
            with app.db_read() as db:visits_after=db.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
            self.assertEqual(visits_after,visits_before) # tutorial lookup did not create an order
            code,_,body=req('GET','/api/hq/stores',cookie=cookie);self.assertEqual(code,200)
            code,_,body=req('POST','/api/hq/stores/create',{'store_id':'BSVH','name':'HTTP测试店','district':'北京','business_type':'鸡尾酒吧','design_max_guests':0},cookie=cookie)
            self.assertEqual(code,403) # must provide CSRF
            code,_,body=req('POST','/api/hq/stores/create',{'store_id':'BSVH','name':'HTTP测试店','district':'北京','business_type':'鸡尾酒吧','design_max_guests':0},cookie=cookie,csrf=csrf)
            self.assertEqual(code,200,body[:400])
        finally:srv.shutdown();srv.server_close();conn.close()
    def test_10_previous_orders_schema_unchanged(self):
        with app.db_read() as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],28)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bsv_layout_ownership').fetchone()[0],3)

if __name__=='__main__':unittest.main()
