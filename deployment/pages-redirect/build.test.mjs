import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { buildRedirect } from "./build.mjs";

test("builds an HTTPS redirect without passing login data or visitor query parameters", async () => {
  const output = await mkdtemp(join(tmpdir(), "ainterior-pages-"));
  try {
    await buildRedirect("https://example.ngrok-free.app", output);
    assert.equal(await readFile(join(output, "redirect.js"), "utf8"), 'location.replace("https://example.ngrok-free.app/");\n');
    assert.match(await readFile(join(output, "index.html"), "utf8"), /rel="noreferrer"/);
  } finally {
    await rm(output, { recursive: true, force: true });
  }
});

test("rejects unsafe or missing destinations", async () => {
  for (const target of [undefined, "http://example.com", "javascript:alert(1)", "https://user:password@example.com", "https://example.com/?token=secret", "https://example.com/#token"]) {
    await assert.rejects(buildRedirect(target));
  }
});