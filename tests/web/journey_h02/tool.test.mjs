import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { externalHttpRequests, sha256File, toHar } from "../../../tools/web_journey_h02/lib.mjs";

test("sha256 uses full lowercase digest", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "h02-"));
  const file = path.join(root, "x");
  await writeFile(file, "H02\n");
  assert.equal(await sha256File(file), "f50452494a85857fc79f1a0518215c2fd6501fa00e09a52bd4769e1947d0443e");
});

test("external request classifier accepts only loopback HTTP", () => {
  const urls = ["http://127.0.0.1:4173/", "http://localhost:8765/api", "https://example.invalid/x", "data:text/plain,x"];
  assert.deepEqual(externalHttpRequests(urls), ["https://example.invalid/x"]);
});

test("HAR builder preserves exact request URL and status", () => {
  const har = toHar([{ startedDateTime: "2026-11-05T00:00:00.000Z", method: "GET", url: "http://127.0.0.1:4173/", status: 200, statusText: "OK", mimeType: "text/html" }]);
  assert.equal(har.log.version, "1.2");
  assert.equal(har.log.entries[0].request.url, "http://127.0.0.1:4173/");
  assert.equal(har.log.entries[0].response.status, 200);
});

