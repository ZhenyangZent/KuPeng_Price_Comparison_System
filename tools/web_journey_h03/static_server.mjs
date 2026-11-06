import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import process from "node:process";

const root = path.resolve(process.argv[2]);
const port = Number(process.argv[3]);
const types = { ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8" };
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, `http://127.0.0.1:${port}`).pathname);
    const candidate = path.resolve(root, pathname === "/" ? "index.html" : `.${pathname}`);
    if (!candidate.startsWith(root + path.sep) && candidate !== root) throw new Error("outside root");
    const info = await stat(candidate);
    if (!info.isFile()) throw new Error("not file");
    response.writeHead(200, { "Content-Type": types[path.extname(candidate)] ?? "application/octet-stream", "Cache-Control": "no-store" });
    createReadStream(candidate).pipe(response);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("not found");
  }
});
server.listen(port, "127.0.0.1", () => console.log(`H03 static server http://127.0.0.1:${port}`));
