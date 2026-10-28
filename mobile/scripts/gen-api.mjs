// Generates the typed API client schema from the backend code (AD-13).
// 1. Dumps the FastAPI OpenAPI schema to a temp file (no server or DB needed).
// 2. Runs openapi-typescript on it into a temp schema file.
// 3. Only when both succeed, moves them to mobile/openapi.json and mobile/src/api/schema.ts.
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const backendDir = join(mobileDir, '..', 'backend');
const openapiPath = join(mobileDir, 'openapi.json');
const schemaPath = join(mobileDir, 'src', 'api', 'schema.ts');
const bin = join(mobileDir, 'node_modules', 'openapi-typescript', 'bin', 'cli.js');

let tmpDir;

function fail(message) {
  console.error(`gen:api: ${message}`);
  if (tmpDir) rmSync(tmpDir, { recursive: true, force: true });
  process.exit(1);
}

/** Describe why a spawned process failed. */
function why(res) {
  if (res.error) return res.error.message;
  return res.status !== null ? `exit ${res.status}` : `signal ${res.signal}`;
}

if (!existsSync(join(backendDir, 'pyproject.toml'))) {
  fail(`backend not found at ${backendDir}`);
}
if (!existsSync(bin)) fail('openapi-typescript is not installed; run npm install');

tmpDir = mkdtempSync(join(tmpdir(), 'cartwise-gen-api-'));
const tmpOpenapi = join(tmpDir, 'openapi.json');
const tmpSchema = join(tmpDir, 'schema.ts');

// The schema goes to the file named in argv[1], so stray stdout output cannot corrupt it.
const py = [
  'import json, sys',
  'from app.main import create_app',
  "open(sys.argv[1], 'w', encoding='utf-8', newline='\\n').write(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + '\\n')",
].join('; ');

const dump = spawnSync(
  'uv',
  ['--directory', backendDir, 'run', '--quiet', 'python', '-c', py, tmpOpenapi],
  { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } },
);
if (dump.error?.code === 'ENOENT') {
  fail('uv is not installed or not on PATH (https://docs.astral.sh/uv/)');
}
if (dump.error || dump.status !== 0) {
  fail(`dumping the OpenAPI schema failed (${why(dump)}):\n${dump.stderr ?? ''}`);
}
try {
  JSON.parse(readFileSync(tmpOpenapi, 'utf8'));
} catch (err) {
  fail(`backend did not write valid JSON: ${err.message}`);
}

const gen = spawnSync(process.execPath, [bin, tmpOpenapi, '-o', tmpSchema], { stdio: 'inherit' });
if (gen.error || gen.status !== 0) fail(`openapi-typescript failed (${why(gen)})`);

copyFileSync(tmpOpenapi, openapiPath);
copyFileSync(tmpSchema, schemaPath);
rmSync(tmpDir, { recursive: true, force: true });
console.log(`gen:api: wrote ${openapiPath} and ${schemaPath}`);
