const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const ROOT_DIR = path.resolve(__dirname, '..');
const DIST_DIR = path.join(ROOT_DIR, 'dist');
const UPDATE_FILE = path.join(DIST_DIR, 'latest-mac.yml');

function fail(message) {
  console.error(`[verify-mac-artifacts] ${message}`);
  process.exit(1);
}

function log(message) {
  console.log(`[verify-mac-artifacts] ${message}`);
}

function run(command, args) {
  execFileSync(command, args, { stdio: 'inherit' });
}

function sha512Base64(filePath) {
  const hash = crypto.createHash('sha512');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('base64');
}

function parseLatestMacYaml(filePath) {
  const text = fs.readFileSync(filePath, 'utf8');
  const parsed = { files: [], path: null, sha512: null };
  let current = null;

  for (const line of text.split(/\r?\n/)) {
    let match = line.match(/^\s*-\s+url:\s+(.+)$/);
    if (match) {
      current = { url: match[1].trim(), sha512: null, size: null };
      parsed.files.push(current);
      continue;
    }

    match = line.match(/^\s+sha512:\s+(.+)$/);
    if (match && current && current.sha512 === null) {
      current.sha512 = match[1].trim();
      continue;
    }

    match = line.match(/^\s+size:\s+(\d+)$/);
    if (match && current && current.size === null) {
      current.size = Number(match[1]);
      continue;
    }

    match = line.match(/^path:\s+(.+)$/);
    if (match) {
      parsed.path = match[1].trim();
      continue;
    }

    match = line.match(/^sha512:\s+(.+)$/);
    if (match) {
      parsed.sha512 = match[1].trim();
    }
  }

  return parsed;
}

function verifyUpdateManifest(macZipFiles) {
  if (!fs.existsSync(UPDATE_FILE)) {
    fail(`latest-mac.yml not found at ${UPDATE_FILE}`);
  }

  const manifest = parseLatestMacYaml(UPDATE_FILE);

  if (manifest.files.length === 0) {
    fail('latest-mac.yml lists no files.');
  }

  // electron-builder가 zip과 dmg를 모두 빌드하면 latest-mac.yml이 둘 다 나열한다.
  // manifest가 참조하는 각 아티팩트(zip/dmg)를 dist에서 찾아 size/sha512를 대조한다.
  for (const entry of manifest.files) {
    const filePath = path.join(DIST_DIR, entry.url);
    if (!fs.existsSync(filePath)) {
      fail(`latest-mac.yml references missing file: ${entry.url}`);
    }
    const stat = fs.statSync(filePath);
    if (entry.size !== stat.size) {
      fail(`Size mismatch for ${entry.url}: manifest=${entry.size}, actual=${stat.size}`);
    }
    if (entry.sha512 !== sha512Base64(filePath)) {
      fail(`sha512 mismatch for ${entry.url}`);
    }
  }

  // mac ZIP은 electron-updater의 기본 업데이트 대상이므로 반드시 manifest에 포함돼야 한다.
  const zipName = path.basename(macZipFiles[0]);
  if (!manifest.files.some((entry) => entry.url === zipName)) {
    fail(`latest-mac.yml does not list the mac ZIP artifact ${zipName}.`);
  }

  // 최상위 default path/sha512 (electron-updater가 실제로 내려받는 대상) 검증.
  if (!manifest.path) {
    fail('latest-mac.yml is missing the default path field.');
  }
  const defaultPath = path.join(DIST_DIR, manifest.path);
  if (!fs.existsSync(defaultPath)) {
    fail(`latest-mac.yml default path does not exist: ${manifest.path}`);
  }
  if (manifest.sha512 !== sha512Base64(defaultPath)) {
    fail(`latest-mac.yml default sha512 does not match ${manifest.path}`);
  }

  log(`latest-mac.yml matches generated artifacts (${manifest.files.length} file(s)).`);
}

function verifyZip(zipPath) {
  log(`Checking ZIP archive ${path.basename(zipPath)}`);
  run('unzip', ['-t', zipPath]);

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sasoo-mac-zip-'));
  try {
    run('ditto', ['-x', '-k', zipPath, tempDir]);

    const appCandidates = fs
      .readdirSync(tempDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && entry.name.endsWith('.app'))
      .map((entry) => path.join(tempDir, entry.name));

    if (appCandidates.length !== 1) {
      fail(`Expected exactly one .app in ${zipPath}, found ${appCandidates.length}`);
    }
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

if (process.platform !== 'darwin') {
  fail(`Artifact verification must run on macOS. Current platform: ${process.platform}`);
}

if (!fs.existsSync(DIST_DIR)) {
  fail(`dist directory not found: ${DIST_DIR}`);
}

const zipFiles = fs
  .readdirSync(DIST_DIR)
  .filter((name) => name.endsWith('-mac.zip'))
  .map((name) => path.join(DIST_DIR, name));

if (zipFiles.length !== 1) {
  fail(`Expected exactly one -mac.zip artifact in dist/, found ${zipFiles.length}.`);
}

verifyUpdateManifest(zipFiles);

for (const zipPath of zipFiles) {
  verifyZip(zipPath);
}

log('macOS ZIP artifacts passed archive extraction and update manifest checks.');
