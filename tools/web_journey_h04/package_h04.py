from __future__ import annotations
import hashlib,json,shutil,stat,tempfile,zipfile
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[2];NAME='CDH_H_R06_001_REVIEW';REL=ROOT/'review/releases'/f'{NAME}.zip';UP=ROOT/'review/00_TO_UPLOAD'/f'{NAME}.zip';RESULT=ROOT/'review/H04/PACKAGE_RESULT.json';PREFIX=f'{NAME}/'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def info(n):
 x=zipfile.ZipInfo(n,(2026,11,5,0,0,0));x.compress_type=zipfile.ZIP_DEFLATED;x.external_attr=0o100644<<16;x.create_system=3;return x
def files():
 out=set()
 for base in (ROOT/'tools/web_journey_h04',ROOT/'tests/web/journey_h04',ROOT/'reports/H04'):
  out.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
 out.add(ROOT/'review/H04/INPUT_READBACK.json')
 e=ROOT/'review/H04/evidence';out.update(p for p in e.rglob('*') if p.is_file() and not any(part.startswith('chrome-') for part in p.relative_to(e).parts))
 return sorted(out,key=lambda p:p.relative_to(ROOT).as_posix().casefold())
def verify(p):
 with zipfile.ZipFile(p) as z:
  bad=z.testzip();ns=[i.filename for i in z.infolist()];m=json.loads(z.read(PREFIX+'MANIFEST.json'));mis=[]
  for x in m['payloads']:
   try:b=z.read(PREFIX+x['path'])
   except KeyError:mis.append(x['path']);continue
   if len(b)!=x['bytes'] or hashlib.sha256(b).hexdigest()!=x['sha256']:mis.append(x['path'])
  declared={PREFIX+'MANIFEST.json'}|{PREFIX+x['path'] for x in m['payloads']};return{'entries':len(ns),'payloads':len(m['payloads']),'crc':'PASS' if bad is None else 'FAIL','mismatch':len(mis),'undeclared':len(set(ns)-declared),'missing':len(declared-set(ns)),'duplicates':len(ns)-len(set(ns)),'case_collisions':len(ns)-len({n.casefold() for n in ns}),'unsafe_paths':sum('\\' in n or PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in ns),'symlinks':sum(stat.S_ISLNK((i.external_attr>>16)&0xffff) for i in z.infolist())}
def main():
 if REL.exists() or UP.exists():raise RuntimeError('immutable H04 delivery already exists')
 fs=files();payloads=[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in fs];manifest={'schema_version':'CDH-H04-R06-REVIEW-MANIFEST-1','task_id':'CDH-H04-V4-SITE-JOURNEY-001','authority':'AUTHORIZED_SYNTHETIC_OFFLINE_R06_H_ONLY','generated_at_utc':datetime.now(timezone.utc).isoformat(),'input_r06_sha256':'99707ec6058e5b9386be20a4993e94b604974b859d197fca91218202a40dfa46','a08_sha256':'5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d','b09_002_sha256':'35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3','status':'READY_FOR_REVIEW_SCOPED_STUB_AWAITING_A09_B10','exact_a09_b10_e2e':'NOT_RUN','payload_count':len(payloads),'payloads':payloads};mb=json.dumps(manifest,ensure_ascii=False,indent=2).encode()+b'\n';REL.parent.mkdir(parents=True,exist_ok=True);UP.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(REL,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for p in fs:z.writestr(info(PREFIX+p.relative_to(ROOT).as_posix()),p.read_bytes())
  z.writestr(info(PREFIX+'MANIFEST.json'),mb)
 shutil.copyfile(REL,UP);gate=verify(REL);rs=sha(REL);us=sha(UP)
 with tempfile.TemporaryDirectory(prefix='h04-replay-',dir=ROOT/'review/H04') as t:
  with zipfile.ZipFile(REL) as z:z.extractall(t)
  mm=0
  for x in manifest['payloads']:
   p=Path(t)/NAME/Path(*PurePosixPath(x['path']).parts);mm+=not(p.is_file() and p.stat().st_size==x['bytes'] and sha(p)==x['sha256'])
 ok=rs==us and REL.read_bytes()==UP.read_bytes() and gate['crc']=='PASS' and all(gate[k]==0 for k in ('mismatch','undeclared','missing','duplicates','case_collisions','unsafe_paths','symlinks')) and mm==0;result={'task_id':manifest['task_id'],'release':str(REL.relative_to(ROOT)).replace('\\','/'),'upload_copy':str(UP.relative_to(ROOT)).replace('\\','/'),'release_sha256':rs,'upload_sha256':us,'identical_copy':rs==us and REL.read_bytes()==UP.read_bytes(),'manifest_sha256':hashlib.sha256(mb).hexdigest(),'integrity':gate,'extracted_replay_mismatch':mm,'status':'PASS' if ok else 'FAIL'};RESULT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));raise SystemExit(0 if ok else 1)
if __name__=='__main__':main()
