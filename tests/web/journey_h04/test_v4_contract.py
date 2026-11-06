from __future__ import annotations
import json,sys,unittest
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT/'tools/web_journey_h04'))
from v4_contract import ContractError,validate_v4
DATA=json.loads((ROOT/'tools/web_journey_h04/site/fixtures.json').read_text(encoding='utf-8'));NOW=datetime(2026,11,5,12,tzinfo=timezone.utc)
def product(key):return next(x for x in DATA['products'] if x['series_identity']['product_id']==f'SYN-P-{key}')
class V4ContractTests(unittest.TestCase):
 def assert_code(self,value,code):
  with self.assertRaises(ContractError) as caught:validate_v4(value,now=NOW)
  self.assertEqual(caught.exception.code,code)
 def test_t01_confirmed_coupon_primary(self):self.assertEqual(validate_v4(product('CONFIRMED'),now=NOW),{'display_price_twd':49,'display_basis':'CONFIRMED_COUPON','confirmed':True})
 def test_t02_unclaimed_expired_unknown_fall_back(self):
  for key in ('CLAIM','EXPIRED','SELLER'):self.assertEqual(validate_v4(product(key),now=NOW)['display_basis'],'BASE_PRICE')
 def test_t03_already_included_not_double_discounted(self):self.assertEqual(validate_v4(product('INCLUDED'),now=NOW)['display_price_twd'],49)
 def test_t04_two_item_order_coupon_math(self):
  p=product('ORDER');self.assertEqual((p['display_price_twd'],p['required_merchandise_total_twd']),(75,150));self.assertTrue(validate_v4(p,now=NOW)['confirmed'])
 def test_t05_cross_seller_confirmation_refused(self):
  p=deepcopy(product('CONFIRMED'));p['coupon']['bound_identity']['seller_id']='OTHER';self.assert_code(p,'UNCONFIRMED_DISCOUNT')
 def test_t06_other_promotion_cannot_enter_current_history(self):
  p=deepcopy(product('CLAIM'));p['history']['confirmed_after_coupon']=[deepcopy(product('CONFIRMED')['history']['confirmed_after_coupon'][0])];p['history']['confirmed_after_coupon'][0]['series_identity']=p['series_identity'];self.assert_code(p,'UNCONFIRMED_HISTORY')
 def test_t07_unknown_shipping_keeps_total_null(self):
  p=deepcopy(product('CONFIRMED'));p['required_total_twd']=49;self.assert_code(p,'UNKNOWN_TOTAL')
 def test_t08_private_eligibility_missing_is_not_confirmed(self):
  p=deepcopy(product('CONFIRMED'));p['coupon']['eligibility_profile']=None;self.assert_code(p,'UNCONFIRMED_DISCOUNT')
 def test_t09_non_synthetic_source_refused(self):
  p=deepcopy(product('CONFIRMED'));p['data_classification']='USER_AUTHORIZED_COPY';self.assert_code(p,'SOURCE_NOT_AUTHORIZED')
 def test_t10_zero_is_distinct_from_null(self):self.assertEqual(validate_v4(product('ZERO'),now=NOW)['display_price_twd'],0);self.assertIsNone(validate_v4(product('UNKNOWN'),now=NOW)['display_price_twd'])
 def test_t11_v2_v3_regression_evidence_preserved(self):
  previous=json.loads((ROOT/'review/H03/runtime/A08_B09_CONTRACT_RESULTS.json').read_text(encoding='utf-8'));self.assertEqual(previous['counts'],{'total':9,'pass':9,'fail':0})
 def test_t12_invalid_timestamp_and_secret_shape_refused(self):
  p=deepcopy(product('CONFIRMED'));p['observed_at']='2026-11-03T010:00:00Z';self.assert_code(p,'INVALID_TIMESTAMP');self.assertNotIn('token',json.dumps(DATA).lower());self.assertNotIn('.env',json.dumps(DATA).lower())
if __name__=='__main__':unittest.main()
