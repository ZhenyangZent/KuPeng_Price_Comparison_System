import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { sha256File, startStaticServer, verifyManifestFiles } from "../../../tools/web_journey_e2e/lib.mjs";

test("sha256File returns the full lowercase digest", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "h01-hash-"));
  const file = path.join(root, "payload.txt");
  await writeFile(file, "H01\n", "utf8");
  assert.equal(await sha256File(file), "19ae4ca05ba4af4774e0519ca8eb9fa80b23f20108e57ad1fcbb01b39b3dffd6");
});

test("manifest verification is fail closed on a byte mismatch", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "h01-manifest-"));
  await mkdir(path.join(root, "dist"));
  await writeFile(path.join(root, "dist", "a.js"), "safe", "utf8");
  const manifest = path.join(root, "manifest.json");
  await writeFile(manifest, JSON.stringify({ files: [{ path: "dist/a.js", sha256: "0".repeat(64), size: 4 }] }));
  const result = await verifyManifestFiles(manifest, root, "dist/");
  assert.equal(result.count, 1);
  assert.equal(result.pass, false);
});

test("static server serves only local files and rejects an invalid path", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "h01-static-"));
  await writeFile(path.join(root, "index.html"), "<!doctype html><title>H01</title>", "utf8");
  const server = await startStaticServer(root, 0);
  try {
    const response = await fetch(`${server.url}/`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), /H01/);
    const invalid = await fetch(`${server.url}/%00`);
    assert.equal(invalid.status, 400);
  } finally {
    await server.close();
  }
});

