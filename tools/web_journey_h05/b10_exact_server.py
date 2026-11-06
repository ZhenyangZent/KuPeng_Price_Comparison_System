from __future__ import annotations
import shutil,sys,tempfile
from pathlib import Path
from wsgiref.simple_server import make_server
ROOT=Path(__file__).resolve().parents[2];B10=ROOT/'review/H05/baselines/B10/CDH_B_R06_001_REVIEW';sys.path.insert(0,str(B10));sys.path.insert(0,str(B10/'services/price_coupon_v4'));sys.path.insert(0,str(B10/'services/price_quality_adapter'));sys.path.insert(0,str(B10/'services/price_query_v3'))
from tests.web.price_coupon_v4.test_coupon_v4 import repository
from price_coupon_v4 import CouponPriceV4App
runtime=ROOT/'review/H05/runtime';runtime.mkdir(parents=True,exist_ok=True);temp=Path(tempfile.mkdtemp(prefix='b10-',dir=runtime));app=CouponPriceV4App(repository(temp));server=make_server('127.0.0.1',8767,app)
print('B10_EXACT_READY http://127.0.0.1:8767',flush=True)
try:server.serve_forever()
finally:shutil.rmtree(temp,ignore_errors=True)
