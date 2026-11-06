from __future__ import annotations
import hashlib,json,re,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];H=ROOT/'review/H04';E=H/'evidence';OUT=E/'H04_VERIFICATION.json'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 inputs=load(H/'INPUT_READBACK.json');ts=load(E/'A08_TIMESTAMP_REPRODUCTION.json');browser=load(E/'BROWSER_JOURNEY.json');har=load(E/'NETWORK_HAR.json');shots=[]
 for item in browser['results']:
  p=ROOT/Path(item['screenshot']);b=p.read_bytes();w,h=struct.unpack('>II',b[16:24]);shots.append({'case':item['case'],'sha256':sha(p),'width':w,'height':h,'pass':item['pass']})
 files=[p for base in (ROOT/'tools/web_journey_h04',ROOT/'tests/web/journey_h04',ROOT/'reports/H04',ROOT/'review/H04/evidence') if base.exists() for p in base.rglob('*') if p.is_file() and p.suffix.lower() not in {'.png','.zip'}];patterns=[re.compile(rb'AKIA[0-9A-Z]{16}'),re.compile(rb'sk-[A-Za-z0-9_-]{20,}'),re.compile(rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.')];hits=[]
 for p in files:
  data=p.read_bytes()
  for pattern in patterns:
   if pattern.search(data):hits.append({'path':str(p.relative_to(ROOT)),'pattern':pattern.pattern.decode()})
 gates={'input_integrity':inputs['status']=='PASS','a08_timestamp_reproduced':ts['reproduced'],'strict_v4_stub':browser['all_pass'] and len(browser['results'])==11,'network_isolation':browser['network']['external_request_count']==0 and har['external_request_count']==0,'cta_disabled':all(x['outbound_anchor_count']==0 and (x['case']=='invalid-timestamp' or x['disabled_cta_count']==1) for x in browser['results']),'secret_scan':not hits,'a09_b10_exact_gate_not_misreported':inputs['inputs']['A09']['state']=='NOT_AVAILABLE' and inputs['inputs']['B10']['state']=='NOT_AVAILABLE' and browser['exact_release_e2e']=='NOT_RUN_A09_B10_NOT_AVAILABLE'}
 result={'task_id':'CDH-H04-V4-SITE-JOURNEY-001','authority':'AUTHORIZED_SYNTHETIC_OFFLINE_R06_H_ONLY','gates':gates,'a08_timestamp':ts,'browser':{'journeys':len(browser['results']),'passed':sum(x['pass'] for x in browser['results']),'external_requests':browser['network']['external_request_count'],'screenshots':shots},'exact_release_e2e':'NOT_RUN_A09_B10_NOT_AVAILABLE','secret_scan_hits':hits,'status':'PASS_SCOPED_STUB_AWAITING_A09_B10' if all(gates.values()) else 'FAIL'};OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'status':result['status'],'gates':gates},ensure_ascii=False));raise SystemExit(0 if result['status'].startswith('PASS') else 1)
if __name__=='__main__':main()
