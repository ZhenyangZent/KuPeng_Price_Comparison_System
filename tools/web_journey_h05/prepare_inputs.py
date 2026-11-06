from __future__ import annotations
import hashlib,json,stat,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'review/H05/baselines';REPORT=ROOT/'review/H05/INPUT_READBACK.json'
SPECS={'R07':(ROOT/'input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R07/CDH_UNIFIED_CONTINUOUS_20261105_R07.zip','76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827','MANIFEST.json','files'),'A09':(ROOT/'review/releases/CDH_A_R06_001_REVIEW.zip','96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde','CDH_A_R06_001_REVIEW/MANIFEST.json','files'),'B10':(ROOT/'review/releases/CDH_B_R06_001_REVIEW.zip','dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549','CDH_B_R06_001_REVIEW/REVIEW_MANIFEST.json','payloads')}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 OUT.mkdir(parents=True,exist_ok=True);result={}
 for label,(src,expected,mname,kind) in SPECS.items():
  if not src.is_file() or sha(src)!=expected:raise RuntimeError(f'{label} missing/SHA mismatch')
  with zipfile.ZipFile(src) as z:
   infos=z.infolist();names=[x.filename for x in infos];bad=z.testzip();m=json.loads(z.read(mname));unsafe=[n for n in names if '\\' in n or PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts];syms=[x.filename for x in infos if stat.S_ISLNK((x.external_attr>>16)&0xffff)]
   if bad or unsafe or syms or len(names)!=len(set(names)) or len(names)!=len({n.casefold() for n in names}):raise RuntimeError(f'{label} unsafe')
   target=OUT/label
   if label!='R07' and not target.exists():target.mkdir();z.extractall(target)
  items=m['files'] if kind=='files' else m['payloads'];mis=[]
  for x in items:
   if label=='R07':
    with zipfile.ZipFile(src) as z:b=z.read(x['path']);ok=len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256']
   else:
    base=(target/mname).parent if kind=='files' else target;p=base/Path(*PurePosixPath(x['path']).parts);size=x.get('size',x.get('bytes'));ok=p.is_file() and p.stat().st_size==size and sha(p)==x['sha256']
   if not ok:mis.append(x['path'])
  if mis:raise RuntimeError(f'{label} manifest mismatch')
  result[label]={'sha256':expected,'entries':len(names),'manifest_declared':len(items),'manifest_mismatch':0,'crc':'PASS','unsafe_paths':0,'symlinks':0}
 candidates={p.name:(sha(p),p.stat().st_size) for p in (ROOT/'review/releases').glob('*.zip') if ('R07' in p.name or 'A10' in p.name or 'B11' in p.name)};result['A10']={'state':'NOT_AVAILABLE'};result['B11']={'state':'NOT_AVAILABLE'}
 for n,(h,s) in candidates.items():
  if n.startswith('CDH_A') and n!='CDH_A_R06_001_REVIEW.zip':result['A10']={'state':'AVAILABLE','filename':n,'sha256':h,'bytes':s}
  if n.startswith('CDH_B') and n!='CDH_B_R06_001_REVIEW.zip':result['B11']={'state':'AVAILABLE','filename':n,'sha256':h,'bytes':s}
 REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps({'status':'PASS','inputs':result},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'status':'PASS','inputs':result}))
if __name__=='__main__':main()
