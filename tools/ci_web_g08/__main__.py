from __future__ import annotations
import argparse, json
from pathlib import Path
from .runner import run

PINS = {"A10": ("CDH_A_R08_001_REVIEW.zip", "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd"), "B11": ("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"), "B12": ("CDH_B_R08_001_REVIEW.zip", "8e04bcec4e7dd82778858043064dd9676597edade17c496ab16a9042e68bc364"), "C09": ("CDH_C_R08_001_REVIEW.zip", "a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7"), "F07": ("CDH_F_R08_001_REVIEW.zip", "705b8cf34a5315e661de443f27346efa3b97670e81f334f59cb6ab9cd2fff2ee")}
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,default=Path.cwd()); parser.add_argument("--run-id",required=True); parser.add_argument("--receipt-ack",type=Path,required=True); args=parser.parse_args(); releases=args.root/"review"/"releases"; inputs={name:(releases/file,digest) for name,(file,digest) in PINS.items()}; report,code=run(root=args.root,run_id=args.run_id,inputs=inputs,receipt_ack=args.receipt_ack); print(json.dumps(report["summary"],sort_keys=True)); return code
if __name__=="__main__": raise SystemExit(main())
