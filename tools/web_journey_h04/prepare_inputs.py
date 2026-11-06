from __future__ import annotations
import hashlib,json,stat,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'review'/'H04'/'baselines'; REPORT=ROOT/'review'/'H04'/'INPUT_READBACK.json'
SPECS={
'R06':(ROOT/'input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R06/CDH_UNIFIED_CONTINUOUS_20261105_R06.zip','99707ec6058e5b9386be20a4993e94b604974b859d197fca91218202a40dfa46','MANIFEST.json','r06'),
'A08':(ROOT/'review/releases/CDH_A08_001_REVIEW.zip','5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d','CDH_A08_001_REVIEW/MANIFEST.json','files'),
'B09_002':(ROOT/'review/releases/CDH_B09_002_REVIEW.zip','35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3','CDH_B09_002_REVIEW/REVIEW_MANIFEST.json','payloads')}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(n):
 p=PurePosixPath(n);return '\\' not in n and not p.is_absolute() and '..' not in p.parts and not(p.parts and ':' in p.parts[0])
def main():
 OUT.mkdir(parents=True,exist_ok=True); result={}
 for label,(src,expected,manifest_name,kind) in SPECS.items():
  if not src.is_file() or sha(src)!=expected:raise RuntimeError(f'{label} SHA mismatch or missing')
  with zipfile.ZipFile(src) as z:
   infos=z.infolist();names=[i.filename for i in infos];bad=z.testzip();m=json.loads(z.read(manifest_name));syms=[i.filename for i in infos if stat.S_ISLNK((i.external_attr>>16)&0xffff)];unsafe=[n for n in names if not safe(n)]
   if bad or len(names)!=len(set(names)) or len(names)!=len({n.casefold() for n in names}) or syms or unsafe:raise RuntimeError(f'{label} unsafe archive')
   target=OUT/label
   if label!='R06' and not target.exists():target.mkdir();z.extractall(target)
  items=m['files'] if kind in {'files','r06'} else m['payloads']; mism=[]
  for x in items:
   if label=='R06': data=zipfile.ZipFile(src).read(x['path']);ok=len(data)==x['bytes'] and hashlib.sha256(data).hexdigest()==x['sha256']
   else:
    base=(target/manifest_name).parent if kind=='files' else target;p=base/Path(*PurePosixPath(x['path']).parts);size=x.get('size',x.get('bytes'));ok=p.is_file() and p.stat().st_size==size and sha(p)==x['sha256']
   if not ok:mism.append(x['path'])
  if mism:raise RuntimeError(f'{label} manifest mismatch: {mism}')
  result[label]={'sha256':expected,'entries':len(names),'crc':'PASS','manifest_declared':len(items),'manifest_mismatch':0,'unsafe_paths':0,'symlinks':0}
 for label,name in [('A09','CDH_A_R06_001_REVIEW.zip'),('B10','CDH_B_R06_001_REVIEW.zip')]:
  p=ROOT/'review/releases'/name;result[label]={'state':'AVAILABLE' if p.is_file() else 'NOT_AVAILABLE','sha256':sha(p) if p.is_file() else None}
 REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps({'status':'PASS','inputs':result},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'status':'PASS','inputs':result}))
if __name__=='__main__':main()
