// Fails when web3 stops calling an API route that web2 calls, so no feature is lost in the move.
// Run from web3/: `node scripts/check-parity.mjs`. Routes web3 deliberately drops go in ALLOWED_GAPS
// with the reason; there are none today.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ALLOWED_GAPS = new Map([
  // ["POST /api/example", "why it is gone"],
]);

const CALL = /client\.(GET|POST|PUT|PATCH|DELETE)\(\s*"([^"]+)"/g;

function calls(dir) {
  const found = new Set();
  const walk = (d) => {
    for (const name of readdirSync(d)) {
      const path = join(d, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(ts|tsx)$/.test(name) && !name.endsWith("schema.ts")) {
        for (const [, method, route] of readFileSync(path, "utf8").matchAll(CALL)) found.add(`${method} ${route}`);
      }
    }
  };
  walk(dir);
  return found;
}

const before = calls("../web2/src");
const after = calls("src");
const missing = [...before].filter((c) => !after.has(c) && !ALLOWED_GAPS.has(c)).sort();
const added = [...after].filter((c) => !before.has(c)).sort();

console.log(`web2 calls ${before.size} routes; web3 calls ${after.size}.`);
if (added.length) console.log(`New in web3:\n  ${added.join("\n  ")}`);
if (missing.length) {
  console.error(`\nweb3 does not yet call ${missing.length} route(s) web2 uses:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log("Parity: every route web2 uses is used by web3.");
