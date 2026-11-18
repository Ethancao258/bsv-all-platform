"""BSV1 checkout ledger queries.

There are two distinct financial events:
- Order line creation / service: not cash received.
- demo_checkouts.created_at: an unverified staff-entered checkout record.

This module reports the latter by Beijing calendar date, including checkouts on
visits that remain OPEN and split payments on different days. It never claims
bank/payment-processor reconciliation.
"""
from __future__ import annotations
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO

BEIJING_TZ = timezone(timedelta(hours=8))

# All components come from the same checkout snapshot linkage.
# A checkout amount must not be duplicated by join fan-out on order_lines.
LEDGER_CTE = '''
WITH checkout_lines AS (
  SELECT checkout_id,
    SUM(CASE WHEN status <> 'CANCELLED' THEN
      quantity * COALESCE(list_price_cents, price_cents + COALESCE(discount_cents,0))
      ELSE 0 END) AS gross_cents,
    SUM(CASE WHEN status <> 'CANCELLED' THEN
      quantity * COALESCE(discount_cents,0) ELSE 0 END) AS discount_cents,
    SUM(CASE WHEN status <> 'CANCELLED' THEN
      quantity * price_cents ELSE 0 END) AS due_cents,
    SUM(CASE WHEN status <> 'CANCELLED' THEN quantity ELSE 0 END) AS item_count
  FROM order_lines
  WHERE checkout_id IS NOT NULL
  GROUP BY checkout_id
), ledger AS (
 SELECT c.id,c.visit_id,c.store_id,c.created_at,c.created_by,
        v.status AS visit_status,v.closed_at,
        s.label AS seat_label,
        c.amount_cents AS registered_cents,
        COALESCE(l.gross_cents,0) AS gross_cents,
        COALESCE(l.discount_cents,0) AS discount_cents,
        COALESCE(l.due_cents,0) AS due_cents,
        COALESCE(l.item_count,0) AS item_count,
        c.amount_cents - COALESCE(l.due_cents,0) AS difference_cents,
        CASE WHEN l.item_count IS NULL THEN 1 ELSE 0 END AS missing_items
 FROM demo_checkouts c
 JOIN visits v ON v.id=c.visit_id AND v.store_id=c.store_id
 JOIN seats s ON s.id=v.seat_id AND s.store_id=v.store_id
 LEFT JOIN checkout_lines l ON l.checkout_id=c.id
)
'''

COLS = 'id,visit_id,store_id,created_at,created_by,visit_status,closed_at,seat_label,registered_cents,gross_cents,discount_cents,due_cents,item_count,difference_cents,missing_items'


def _where(store_id, start, end):
    predicates=['store_id=?']
    args=[store_id]
    if start:
        predicates.append('created_at>=?');args.append(start)
    if end:
        predicates.append('created_at<?');args.append(end)
    return ' WHERE ' + ' AND '.join(predicates), args


def checkout_report(db, store_id, start=None, end=None, offset=0, page_size=100):
    """Full-range totals; paginated per-checkout records; no 300-row totals truncation."""
    if not isinstance(offset,int) or offset<0 or offset>100_000_000:raise ValueError('offset out of range')
    if not isinstance(page_size,int) or not 1<=page_size<=200:raise ValueError('page size out of range')
    where,args=_where(store_id,start,end)
    totals_sql=LEDGER_CTE+'''
    SELECT COUNT(*) AS checkout_count,
     COALESCE(SUM(gross_cents),0) AS gross_cents,
     COALESCE(SUM(discount_cents),0) AS discount_cents,
     COALESCE(SUM(due_cents),0) AS due_cents,
     COALESCE(SUM(registered_cents),0) AS registered_cents,
     COALESCE(SUM(difference_cents),0) AS difference_cents,
     COALESCE(SUM(CASE WHEN difference_cents<>0 THEN 1 ELSE 0 END),0) AS mismatch_count,
     COALESCE(SUM(missing_items),0) AS missing_items_count,
     COUNT(DISTINCT visit_id) AS visit_count
    FROM ledger '''+where
    summary=dict(db.execute(totals_sql,args).fetchone())
    daily_sql=LEDGER_CTE+'''
    SELECT substr(datetime(created_at, '+8 hours'),1,10) AS date,
      COUNT(*) AS checkout_count,COUNT(DISTINCT visit_id) AS visit_count,
      COALESCE(SUM(gross_cents),0) AS gross_cents,
      COALESCE(SUM(discount_cents),0) AS discount_cents,
      COALESCE(SUM(due_cents),0) AS due_cents,
      COALESCE(SUM(registered_cents),0) AS registered_cents,
      COALESCE(SUM(difference_cents),0) AS difference_cents,
      COALESCE(SUM(CASE WHEN difference_cents<>0 THEN 1 ELSE 0 END),0) AS mismatch_count
    FROM ledger '''+where+' GROUP BY 1 ORDER BY 1 DESC'
    daily=[dict(x) for x in db.execute(daily_sql,args)]
    record_sql=LEDGER_CTE+' SELECT '+COLS+' FROM ledger '+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?'
    records=[dict(x) for x in db.execute(record_sql, args+[page_size,offset])]
    return {'store_id':store_id,'basis':'checkout_created_at_Asia_Shanghai',
            'verified_payment':False,'summary':summary,'report':daily,
            'checkouts':records,'offset':offset,'page_size':page_size,
            'has_more':offset+len(records)<summary['checkout_count']}


def checkout_csv_bytes(db, store_id, start=None, end=None):
    """Export every matching checkout, not a truncated screen page; no third-party libs."""
    where,args=_where(store_id,start,end)
    rows=db.execute(LEDGER_CTE+' SELECT '+COLS+' FROM ledger '+where+' ORDER BY created_at,id',args)
    out=StringIO(newline='')
    writer=csv.writer(out,lineterminator='\r\n')
    writer.writerow(['门店ID','结账登记ID','桌次ID','座位','登记时间(北京时间)','桌次状态',
                     '商品数量','账面金额(元)','优惠金额(元)','折后应收(元)',
                     '已登记结账(元)','登记差额(元)','订单行缺失','支付核验状态'])
    for r in rows:
        iso=datetime.fromisoformat(r['created_at']).astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
        def m(x):return f'{int(x)/100:.2f}'
        # Identifiers and seat labels are fixed internal identifiers, but still
        # sanitize against spreadsheet formula injection before writing CSV.
        def safe(x):
            value=str(x or '')
            return "'"+value if value[:1] in ('=','+','-','@','\t','\r') else value
        writer.writerow([safe(r['store_id']),safe(r['id']),safe(r['visit_id']),safe(r['seat_label']),
                         iso,safe(r['visit_status']),r['item_count'],m(r['gross_cents']),
                         m(r['discount_cents']),m(r['due_cents']),m(r['registered_cents']),
                         m(r['difference_cents']),r['missing_items'],'未核验（非到账证明）'])
    return out.getvalue().encode('utf-8-sig')
