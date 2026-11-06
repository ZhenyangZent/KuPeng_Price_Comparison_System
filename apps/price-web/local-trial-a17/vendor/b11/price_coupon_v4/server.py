from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from wsgiref.simple_server import make_server

from .api import CouponPriceV4App
from .repository import CouponPriceRepository


def _loopback_origin(value: str) -> str:
    parsed=urlparse(value)
    if parsed.scheme!="http" or parsed.hostname not in {"127.0.0.1","localhost"} or parsed.username or parsed.password or parsed.path not in {"","/"} or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("allowed origin must be an http loopback origin without path/query/credentials")
    if parsed.port is None: raise argparse.ArgumentTypeError("allowed origin must include an explicit port")
    return value.rstrip("/")


def create_app(database:Path,authority:Path,fixture_root:Path,*,allowed_origins:tuple[str,...]=())->CouponPriceV4App:
    repository=CouponPriceRepository(database,authority_file=authority,allowed_root=fixture_root)
    return CouponPriceV4App(repository,allowed_origins=allowed_origins)


def parser()->argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="B11 synthetic/offline loopback V4 server")
    value.add_argument("--database-copy",type=Path,required=True); value.add_argument("--authority-file",type=Path,required=True); value.add_argument("--fixture-root",type=Path,required=True)
    value.add_argument("--host",default="127.0.0.1",choices=("127.0.0.1",)); value.add_argument("--port",type=int,default=8766); value.add_argument("--allowed-origin",action="append",default=[],type=_loopback_origin); value.add_argument("--check",action="store_true")
    return value


def main(argv:list[str]|None=None)->int:
    args=parser().parse_args(argv)
    if not 1<=args.port<=65535: parser().error("port must be between 1 and 65535")
    app=create_app(args.database_copy,args.authority_file,args.fixture_root,allowed_origins=tuple(args.allowed_origin))
    if args.check:
        print(json.dumps({"status":"READY","schema_version":"CDH-COUPON-PRICE-V4","bind_host":args.host,"port":args.port,"allowed_origins":args.allowed_origin,"data_version":app.repository.data_version},sort_keys=True)); return 0
    with make_server(args.host,args.port,app) as server:
        print(f"B11 synthetic V4 listening on http://{args.host}:{args.port}",flush=True); server.serve_forever()
    return 0


if __name__=="__main__": raise SystemExit(main())
