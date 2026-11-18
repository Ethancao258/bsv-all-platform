import pytest
from services.api.supply.domain import calc_reorder,validate_count,unique_codes

def args(**overrides):
    x=dict(confirmed_available='8',usage_before_next='3',arrivals_before_next='0',reserved='0',
           expiry_before_next='0',demand_next_cycle='10',safety_stock='2',arrivals_next_cycle='0',pack_size='1')
    x.update(overrides);return x

def test_replenishment():
    o=calc_reorder(**args())
    assert o['packages']==7 and o['status']=='SUGGESTED' and o['expected_stock_before']=='5'
    o=calc_reorder(**args(pack_size='4'))
    assert o['packages']==2 and o['quantity']=='8'
    assert calc_reorder(**args(reliable=False))['status']=='REVIEW_REQUIRED'
    assert calc_reorder(**args(max_packs=5))['status']=='REVIEW_REQUIRED'
    with pytest.raises(ValueError):calc_reorder(**args(confirmed_available='-1'))

def test_bucket_is_not_exact():
    v=validate_count(2,50,1)
    assert v['estimated_packages']=='2.5' and v['exact'] is False
    assert validate_count(1,None,2)['method']=='UNKNOWN'
    with pytest.raises(ValueError):validate_count(1,30,1)
    with pytest.raises(ValueError):validate_count(-1,0,0)

def test_scans():
    with pytest.raises(ValueError):unique_codes(['X','X'])
    with pytest.raises(ValueError):unique_codes([])
    assert unique_codes([' PKG-1 '])==['PKG-1']
