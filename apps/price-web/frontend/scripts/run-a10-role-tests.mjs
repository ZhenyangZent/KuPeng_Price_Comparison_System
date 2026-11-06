import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
const frontendRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");const projectRoot=path.resolve(frontendRoot,"../../..");const testTemp=path.join(projectRoot,"reports","A10","test_tmp_a10_role");const vitest=path.join(frontendRoot,"node_modules","vitest","vitest.mjs");await mkdir(testTemp,{recursive:true});const child=spawn(process.execPath,[vitest,"run","--config",path.join(frontendRoot,"vite.a10.config.ts")],{cwd:projectRoot,env:{...process.env,TEMP:testTemp,TMP:testTemp},shell:false,stdio:"inherit",windowsHide:true});child.on("exit",(code,signal)=>{if(signal)process.kill(process.pid,signal);process.exitCode=code??1;});
