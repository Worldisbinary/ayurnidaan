// CI gate over `npm audit`: fail on any high/critical advisory that is not in
// audit-allowlist.json, and on allowlist entries that have expired or are no longer needed
// (so the list cannot rot). Usage: node scripts/audit-gate.mjs
import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const BLOCKING = new Set(['high', 'critical']);
const allow = JSON.parse(readFileSync(new URL('../audit-allowlist.json', import.meta.url), 'utf8'));
const today = new Date().toISOString().slice(0, 10);

let raw;
try {
  raw = execSync('npm audit --json', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
} catch (err) {
  raw = err.stdout; // npm audit exits non-zero whenever it finds anything
}
const report = JSON.parse(raw);

const found = new Map(); // GHSA id -> {severity, name, url}
for (const vuln of Object.values(report.vulnerabilities ?? {})) {
  for (const via of vuln.via) {
    if (typeof via !== 'object') continue;
    const id = via.url.split('/').pop();
    found.set(id, { severity: via.severity, name: via.name, url: via.url });
  }
}

const problems = [];
const allowed = new Map(allow.advisories.map((a) => [a.id, a]));
for (const [id, adv] of found) {
  if (!BLOCKING.has(adv.severity)) continue;
  const entry = allowed.get(id);
  if (!entry) problems.push(`NEW ${adv.severity} ${adv.name} ${adv.url}`);
  else if (entry.expires < today) problems.push(`EXPIRED allowlist entry ${id} (${entry.package}, ${entry.expires}) - re-review`);
}
for (const entry of allow.advisories) {
  if (!found.has(entry.id)) problems.push(`STALE allowlist entry ${entry.id} (${entry.package}) is fixed - remove it`);
}

const counts = report.metadata?.vulnerabilities ?? {};
console.log(`npm audit: ${JSON.stringify(counts)}; ${found.size} distinct advisories, ${allowed.size} allowlisted`);
if (problems.length) {
  console.error(problems.map((p) => `  - ${p}`).join('\n'));
  process.exit(1);
}
console.log('audit gate passed');
