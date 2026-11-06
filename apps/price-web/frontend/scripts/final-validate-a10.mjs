import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
const frontendRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");const projectRoot=path.resolve(frontendRoot,"../../..");const logRoot=path.join(projectRoot,"reports","A10","logs");await mkdir(logRoot,{recursive:true});
function execute(name,script,args=[]){return new Promise((resolve,reject)=>{const child=spawn(process.execPath,[script,...args],{cwd:frontendRoot,env:process.env,shell:false,windowsHide:true});let stdout="",stderr="";child.stdout.on("data",data=>{stdout+=data.toString();process.stdout.write(data);});child.stderr.on("data",data=>{stderr+=data.toString();process.stderr.write(data);});child.on("error",reject);child.on("close",async code=>{const record={name,command:`node ${path.relative(frontendRoot,script)} ${args.join(" ")}`.trim(),exit_code:code,stdout,stderr};await writeFile(path.join(logRoot,`${name}.json`),`${JSON.stringify(record,null,2)}\n`,"utf8");resolve(record);});});}
const stages=[
  ["TYPECHECK",path.join(frontendRoot,"node_modules","typescript","bin","tsc"),["-b"]],
  ["BUILD",path.join(frontendRoot,"node_modules","vite","bin","vite.js"),["build"]],
  ["UNIT_TESTS",path.join(frontendRoot,"scripts","run-tests.mjs"),[]],
  ["A07_ROLE_PATH_TESTS",path.join(frontendRoot,"scripts","run-role-tests.mjs"),[]],
  ["A08_ROLE_PATH_TESTS",path.join(frontendRoot,"scripts","run-a08-role-tests.mjs"),[]],
  ["A09_ROLE_PATH_TESTS",path.join(frontendRoot,"scripts","run-a09-role-tests.mjs"),[]],
  ["A10_ROLE_PATH_TESTS",path.join(frontendRoot,"scripts","run-a10-role-tests.mjs"),[]],
  ["B11_ACTUAL_WSGI_HEADLESS_E2E",path.join(frontendRoot,"scripts","headless-e2e.mjs"),[]]
];const results=[];for(const[name,script,args]of stages){if(results.some(result=>result.exit_code!==0))break;results.push(await execute(name,script,args));}
const summary={task_id:"CDH-A10-B10-ACTUAL-API-UI-INTEGRATION-001",created_at_utc:new Date().toISOString(),b10_release_sha256:"dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549",b11_release_sha256:"6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",b11_exact_integration:results.length===stages.length&&results.every(result=>result.exit_code===0)?"PASS":"FAIL",results:results.map(({name,command,exit_code})=>({name,command,exit_code})),all_pass:results.length===stages.length&&results.every(result=>result.exit_code===0)};await writeFile(path.join(logRoot,"FINAL_VALIDATION.json"),`${JSON.stringify(summary,null,2)}\n`,"utf8");console.log(JSON.stringify(summary));process.exitCode=summary.all_pass?0:1;
