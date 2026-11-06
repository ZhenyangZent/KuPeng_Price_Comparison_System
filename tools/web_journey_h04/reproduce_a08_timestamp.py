from __future__ import annotations
import hashlib,json,re
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'review/H04/baselines/A08/CDH_A08_001_REVIEW/apps/price-web/frontend/src/fixtures.ts';OUT=ROOT/'review/H04/evidence/A08_TIMESTAMP_REPRODUCTION.json';EXPECTED='42b4b847a3a4382eb024612c5888df4a8da52a4a1067c4c567fc6207afe57d37'
def main():
 text=SRC.read_text(encoding='utf-8');actual=hashlib.sha256(SRC.read_bytes()).hexdigest();pattern='2026-11-0${i+1}T0${i+8}:00:00Z';generated=[f'2026-11-0{i+1}T0{i+8}:00:00Z' for i in range(3)];valid=[]
 for value in generated:
  try:datetime.fromisoformat(value.replace('Z','+00:00'));valid.append(True)
  except ValueError:valid.append(False)
 result={'task_id':'CDH-H04-V4-SITE-JOURNEY-001','a08_zip_sha256':'5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d','source_sha256':actual,'source_sha_match':actual==EXPECTED,'generator_pattern_present':pattern in text,'generated':generated,'valid':valid,'reproduced':actual==EXPECTED and pattern in text and valid==[True,True,False],'defect_id':'P2-A-A08-T010'};OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));raise SystemExit(0 if result['reproduced'] else 1)
if __name__=='__main__':main()
