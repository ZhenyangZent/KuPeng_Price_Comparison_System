from __future__ import annotations
import argparse
from pathlib import Path
from .runner import run
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=Path.cwd());p.add_argument("--run-id",required=True);p.add_argument("--headless",action="store_true");a=p.parse_args();_,code=run(a.root,a.run_id,a.headless);return code
if __name__=="__main__":raise SystemExit(main())
