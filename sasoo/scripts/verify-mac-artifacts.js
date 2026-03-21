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

function verifyUpdateManifest(zipFiles, dmgFiles) {
  if (!fs.existsSync(UPDATE_FILE)) {
    fail(`latest-mac.yml not found at ${UPDATE_FILE}`);
  }

  const manifest = parseLatestMacYaml(UPDATE_FILE);
  const knownFiles = new Map();

  for (const filePath of [...zipFiles, ...dmgFiles]) {
    const stat = fs.statSync(filePath);
    knownFiles.set(path.basename(filePath), {
      path: filePath,
      size: stat.size,
      sha512: sha512Base64(filePath),
    });
  }

  if (manifest.files.length !== knownFiles.size) {
    fail(`latest-mac.yml lists ${manifest.files.length} files, but dist has ${knownFiles.size} mac artifacts.`);
  }

  for (const entry of manifest.files) {
    const file = knownFiles.get(entry.url);
    if (!file) {
      fail(`latest-mac.yml references missing file: ${entry.url}`);
    }
    if (entry.size !== file.size) {
      fail(`Size mismatch for ${entry.url}: manifest=${entry.size}, actual=${file.size}`);
    }
    if (entry.sha512 !== file.sha512) {
      fail(`sha512 mismatch for ${entry.url}`);
    }
  }

  const defaultFile = knownFiles.get(manifest.path);
  if (!defaultFile) {
    fail(`latest-mac.yml default path does not exist: ${manifest.path}`);
  }
  if (manifest.sha512 !== defaultFile.sha512) {
    fail(`latest-mac.yml default sha512 does not match ${manifest.path}`);
  }

  log('latest-mac.yml matches generated artifacts.');
}

function verifyZip(zipPath) {
  log(`Checking ZIP archive ${path.basename(zipPath)}`);
  run('unzip', ['-t', zipPath]);

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sasoo-mac-zip-'));
  run('ditto', ['-x', '-k', zipPath, tempDir]);

  const appCandidates = fs
    .readdirSync(tempDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.endsWith('.app'))
    .map((entry) => path.join(tempDir, entry.name));

  if (appCandidates.length !== 1) {
    fail(`Expected exactly one .app in ${zipPath}, found ${appCandidates.length}`);
  }

  const appPath = appCandidates[0];
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=4', appPath]);
  run('spctl', ['-a', '-vv', '--type', 'exec', appPath]);
}

function verifyDmg(dmgPath) {
  log(`Checking DMG archive ${path.basename(dmgPath)}`);
  run('hdiutil', ['verify', dmgPath]);
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

const dmgFiles = fs
  .readdirSync(DIST_DIR)
  .filter((name) => name.endsWith('.dmg'))
  .map((name) => path.join(DIST_DIR, name));

if (zipFiles.length === 0 || dmgFiles.length === 0) {
  fail('Expected both .dmg and -mac.zip artifacts in dist/.');
}

verifyUpdateManifest(zipFiles, dmgFiles);

for (const zipPath of zipFiles) {
  verifyZip(zipPath);
}

for (const dmgPath of dmgFiles) {
  verifyDmg(dmgPath);
}

log('macOS artifacts passed archive, signature, Gatekeeper, and manifest checks.');
