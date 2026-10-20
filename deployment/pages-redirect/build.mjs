import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

export async function buildRedirect(appUrl, outputDirectory = "dist") {
  const target = new URL(appUrl);
  if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash) {
    throw new Error("APP_URL must be an HTTPS application URL without credentials, query or fragment");
  }
  const jsonTarget = JSON.stringify(target.href).replaceAll("<", "\\u003c").replaceAll(">", "\\u003e").replaceAll("&", "\\u0026");
  const htmlTarget = target.href.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  await mkdir(outputDirectory, { recursive: true });
  await writeFile(resolve(outputDirectory, "index.html"), `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>AInterior</title><script src="./redirect.js" defer></script></head>
<body><main><h1>AInterior</h1><p><a href="${htmlTarget}" rel="noreferrer">Open AInterior</a></p></main></body></html>\n`);
  await writeFile(resolve(outputDirectory, "redirect.js"), `location.replace(${jsonTarget});\n`);
  await writeFile(resolve(outputDirectory, ".nojekyll"), "");
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  await buildRedirect(process.env.APP_URL);
}