from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from tools.ci_web_g04.audit import audit_zip, safe_extract, sha256_file
from tools.ci_web_g04.runner import _find_root

from .security_gate import inspect


A08_SHA="5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d"
B09_002_SHA="35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3"


def _redact(text: str, root: Path) -> str:
    values=(str(root),str(root).replace("\\","/"),str(Path.home()),str(Path.home()).replace("\\","/"))
    for value in sorted(values,key=len,reverse=True): text=text.replace(value,"<PROJECT_ROOT>" if value.casefold().startswith(str(root).casefold()) else "<USER_HOME>")
    return text


def _run(name: str, command: list[str], cwd: Path, logs: Path, root: Path, env: dict[str,str], missing: str|None=None, timeout: int=480) -> dict:
    result={"name":name,"command":[_redact(str(x),root) for x in command],"cwd":str(cwd.relative_to(root)) if cwd.is_relative_to(root) else "<ISOLATED>","status":None,"return_code":None,"duration_seconds":0.0,"reason":None}
    if missing: result.update(status="NOT_RUN_DEPENDENCY",reason=missing);return result
    logs.mkdir(parents=True,exist_ok=True);out,err=logs/f"{name}.stdout.log",logs/f"{name}.stderr.log";started=time.monotonic();run_env=os.environ.copy();run_env.update(env)
    try:
        done=subprocess.run(command,cwd=cwd,env=run_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",timeout=timeout,shell=False,check=False)
        out.write_text(_redact(done.stdout,root),encoding="utf-8");err.write_text(_redact(done.stderr,root),encoding="utf-8")
        result.update(status="PASS" if done.returncode==0 else "FAIL",return_code=done.returncode,duration_seconds=round(time.monotonic()-started,6),stdout_log=str(out.relative_to(root)),stderr_log=str(err.relative_to(root)))
        if done.returncode: result["reason"]=f"process exited with {done.returncode}"
    except (OSError,subprocess.TimeoutExpired) as exc: result.update(status="ERROR",reason=_redact(str(exc),root),duration_seconds=round(time.monotonic()-started,6))
    return result


def _write_outputs(report_dir: Path, report: dict) -> None:
    suites=report["suites"];root=ET.Element("testsuite",name="cdh-g05",tests=str(len(suites)),failures=str(sum(x["status"]=="FAIL" for x in suites)),errors=str(sum(x["status"]=="ERROR" for x in suites)),skipped=str(sum(x["status"]=="NOT_RUN_DEPENDENCY" for x in suites)))
    for item in suites:
        node=ET.SubElement(root,"testcase",classname="tools.ci_web_g05",name=item["name"],time=str(item.get("duration_seconds",0)))
        if item["status"]=="FAIL":ET.SubElement(node,"failure",message=item.get("reason")or"failure")
        elif item["status"]=="ERROR":ET.SubElement(node,"error",message=item.get("reason")or"error")
        elif item["status"]=="NOT_RUN_DEPENDENCY":ET.SubElement(node,"skipped",message=item.get("reason")or"dependency missing")
    ET.indent(root,space="  ");ET.ElementTree(root).write(report_dir/"result.junit.xml",encoding="utf-8",xml_declaration=True)
    rows="".join(f"<tr><td>{html.escape(x['name'])}</td><td>{html.escape(x['status'])}</td><td>{html.escape(str(x.get('return_code')))}</td></tr>"for x in suites)
    sec=report["security_gate"]
    (report_dir/"result.html").write_text("<!doctype html><meta charset='utf-8'><title>CDH G05 V4 preflight</title><style>body{font:15px system-ui;margin:2rem;color:#172033}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd;padding:.5rem;text-align:left}th{background:#eef3f8}</style><h1>G05 V4 preflight</h1><p>Status: "+html.escape(report["summary"]["status"])+"</p><p>V4 matrix: "+html.escape(json.dumps(report["v4_matrix"]["summary"]))+"</p><p>Security: "+html.escape(json.dumps(sec))+"</p><table><tr><th>Suite</th><th>Status</th><th>RC</th></tr>"+rows+"</table>",encoding="utf-8")


def run(root: Path, run_id: str, include_headless: bool) -> tuple[dict,int]:
    root=root.resolve();report_dir=root/"reports"/"G05"/"runs"/run_id;isolation=root/"review"/"G05"/"runs"/run_id;report_dir.mkdir(parents=True,exist_ok=True);isolation.mkdir(parents=True,exist_ok=True)
    front_zip=root/"review"/"releases"/"CDH_A08_001_REVIEW.zip";back_zip=root/"review"/"releases"/"CDH_B09_002_REVIEW.zip"
    audits=[audit_zip(front_zip,A08_SHA),audit_zip(back_zip,B09_002_SHA)]
    for item in audits:item["path"]=str(Path(item["path"]).relative_to(root))
    if not all(item["passed"] for item in audits):
        report={"schema":"CDH-G05-PREFLIGHT-1","summary":{"status":"SECURITY_FAILURE","return_code":4},"audits":audits,"suites":[]};(report_dir/"result.json").write_text(json.dumps(report,indent=2)+"\n");return report,4
    fe,be=isolation/"frontend",isolation/"backend";safe_extract(front_zip,fe);safe_extract(back_zip,be);front_root=_find_root(fe,Path("apps/price-web/frontend"));back_root=_find_root(be,Path("services/price_query_v3"));frontend=front_root/"apps"/"price-web"/"frontend"
    local=root/"apps"/"price-web"/"frontend";modules=local/"node_modules";lock=local/"package-lock.json";node_ok=modules.is_dir() and lock.is_file() and sha256_file(lock)==sha256_file(frontend/"package-lock.json")
    if node_ok and not(frontend/"node_modules").exists():os.symlink(modules,frontend/"node_modules",target_is_directory=True)
    node,npm=shutil.which("node"),shutil.which("npm") or shutil.which("npm.cmd");ts=modules/"typescript"/"lib"/"typescript.js";chrome=next((str(p) for p in (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),Path("/usr/bin/google-chrome"),Path("/usr/bin/chromium")) if p.is_file()),None)
    tmp=isolation/"tmp";tmp.mkdir(parents=True,exist_ok=True);env={"CDH_OFFLINE":"1","NO_PROXY":"*","HTTP_PROXY":"","HTTPS_PROXY":"","TEMP":str(tmp),"TMP":str(tmp),"CDH_CHROME_PATH":chrome or ""};logs=report_dir/"logs"
    old_fixture=isolation/"old_contract.json";old_result=report_dir/"old_contract.json";v4_matrix=report_dir/"v4_matrix.json"
    suites=[
      _run("g05_self_tests",[sys.executable,"-m","unittest","discover","-s","tests/ci_web_g05","-v"],root,logs,root,env),
      _run("b09_002_tests",[sys.executable,"-m","unittest","discover","-s","tests/web/price_query_v3","-p","test_*.py","-v"],back_root,logs,root,env),
      _run("build_old_contract",[sys.executable,"-m","tools.ci_web_g04.fixture_builder","--backend-root",str(back_root),"--output",str(old_fixture),"--temp-root",str(isolation/"old_tmp")],root,logs,root,env),
      _run("emit_v4_matrix",[sys.executable,"-m","tools.ci_web_g05.emit_matrix","--output",str(v4_matrix)],root,logs,root,env),
    ]
    node_missing=None if node and npm and node_ok and ts.is_file() and suites[2]["status"]=="PASS" else "exact lock-matched Node/TypeScript dependencies unavailable"
    suites.extend([
      _run("old_contract_9_of_9",[node or"node",str(root/"tools"/"ci_web_g04"/"evaluate_contract.cjs"),str(ts),str(frontend),str(old_fixture),str(old_result),"canonical-fixed",str(isolation/"compiled")],root,logs,root,env,node_missing),
      _run("a08_vitest",[node or"node","node_modules/vitest/vitest.mjs","run","--reporter=verbose"],frontend,logs,root,env,node_missing),
      _run("a08_role_tests",[npm or"npm","run","test:role"],frontend,logs,root,env,node_missing),
      _run("a08_build",[npm or"npm","run","build"],frontend,logs,root,env,node_missing),
    ])
    if include_headless:suites.append(_run("a08_headless",[node or"node","scripts/headless-e2e.mjs"],frontend,logs,root,env,None if node_missing is None and chrome else "Chrome or exact frontend dependencies unavailable"))
    security=inspect(frontend,back_root);(report_dir/"security_gate.json").write_text(json.dumps(security,indent=2)+"\n",encoding="utf-8")
    states=[x["status"] for x in suites];code=6 if"ERROR"in states else 2 if"FAIL"in states else 3 if"NOT_RUN_DEPENDENCY"in states else 0
    old=json.loads(old_result.read_text(encoding="utf-8")) if old_result.exists() else None;matrix=json.loads(v4_matrix.read_text(encoding="utf-8")) if v4_matrix.exists() else None
    expected_p2=security["csp_gate"]=="FAIL" and security["backend_header_gate"]=="FAIL" and security["url_leak_gate"]=="PASS"
    if not expected_p2 and code==0:code=2
    report={"schema":"CDH-G05-PREFLIGHT-1","task_id":"CDH-G05-V4-CI-PREFLIGHT-001","authority":"AUTHORIZED_SYNTHETIC_OFFLINE_R06_G_ONLY","generated_at_utc":datetime.now(timezone.utc).isoformat(),"run_id":run_id,"platform":{"system":platform.system(),"python":platform.python_version(),"node":bool(node),"npm":bool(npm),"chrome":bool(chrome)},"inputs":{"A08":A08_SHA,"B09_002":B09_002_SHA},"audits":audits,"dependency_lock_match":node_ok,"suites":suites,"old_contract":old,"v4_matrix":matrix,"security_gate":security,"v4_headless_status":"NOT_RUN_INPUT_UNAVAILABLE" if include_headless else "NOT_RUN_NOT_REQUESTED","counters":{"package_install_count":0,"external_network_access_count":0,"env_read_count":0,"production_db_access_count":0,"real_coupon_action_count":0,"deployment_count":0},"summary":{"status":"PASS_WITH_KNOWN_SECURITY_P2" if code==0 else "FAIL","return_code":code,"suite_count":len(suites),"pass_count":states.count("PASS"),"fail_count":states.count("FAIL"),"not_run_dependency_count":states.count("NOT_RUN_DEPENDENCY"),"known_security_p2":expected_p2}}
    (report_dir/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _write_outputs(report_dir,report)
    return report,code
