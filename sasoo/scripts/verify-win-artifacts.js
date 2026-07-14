const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT_DIR = path.resolve(__dirname, '..');
const DIST_DIR = path.join(ROOT_DIR, 'dist');
const UPDATE_FILE = path.join(DIST_DIR, 'latest.yml');

function fail(message) {
  console.error(`[verify-win-artifacts] ${message}`);
  process.exit(1);
}

function log(message) {
  console.log(`[verify-win-artifacts] ${message}`);
}

function sha512Base64(filePath) {
  const hash = crypto.createHash('sha512');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('base64');
}

function normalizeArtifactName(name) {
  return decodeURIComponent(name).replace(/\s+/g, '-');
}

function parseLatestYaml(filePath) {
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

function verifyPortableExecutable(exePath) {
  const header = fs.readFileSync(exePath);
  if (header.length < 2 || header[0] !== 0x4d || header[1] !== 0x5a) {
    fail(`${path.basename(exePath)} is not a valid PE executable (missing MZ header).`);
  }
}

function verifyAuthenticodeSignature(exePath) {
  const script = '$signature = Get-AuthenticodeSignature -LiteralPath $args[0]; if ($signature.Status -ne "Valid") { Write-Error "Invalid Authenticode status: $($signature.Status)"; exit 1 }';
  const { execFileSync } = require('child_process');
  execFileSync('powershell.exe', ['-NoProfile', '-Command', script, exePath], { stdio: 'inherit' });
}

function verifyUpdateManifest(installerPaths) {
  if (!fs.existsSync(UPDATE_FILE)) {
    fail(`latest.yml not found at ${UPDATE_FILE}`);
  }

  const manifest = parseLatestYaml(UPDATE_FILE);
  const knownFiles = new Map();

  for (const filePath of installerPaths) {
    const stat = fs.statSync(filePath);
    const basename = path.basename(filePath);
    const record = {
      path: filePath,
      size: stat.size,
      sha512: sha512Base64(filePath),
    };
    knownFiles.set(basename, record);
    knownFiles.set(normalizeArtifactName(basename), record);
  }

  if (manifest.files.length !== installerPaths.length) {
    fail(`latest.yml lists ${manifest.files.length} files, but dist has ${installerPaths.length} installer artifacts.`);
  }

  for (const entry of manifest.files) {
    const file = knownFiles.get(entry.url);
    if (!file) {
      fail(`latest.yml references missing file: ${entry.url}`);
    }
    if (entry.size !== file.size) {
      fail(`Size mismatch for ${entry.url}: manifest=${entry.size}, actual=${file.size}`);
    }
    if (entry.sha512 !== file.sha512) {
      fail(`sha512 mismatch for ${entry.url}`);
    }
  }

  const defaultFile = knownFiles.get(manifest.path) || knownFiles.get(normalizeArtifactName(manifest.path));
  if (!defaultFile) {
    fail(`latest.yml default path does not exist: ${manifest.path}`);
  }
  if (manifest.sha512 !== defaultFile.sha512) {
    fail(`latest.yml default sha512 does not match ${manifest.path}`);
  }

  log('latest.yml matches generated artifacts.');
}

if (process.platform !== 'win32') {
  fail(`Artifact verification must run on Windows. Current platform: ${process.platform}`);
}

if (!fs.existsSync(DIST_DIR)) {
  fail(`dist directory not found: ${DIST_DIR}`);
}

const exeFiles = fs
  .readdirSync(DIST_DIR)
  .filter((name) => name.endsWith('.exe'))
  .map((name) => path.join(DIST_DIR, name));

if (exeFiles.length !== 1) {
  fail(`Expected exactly one .exe artifact in dist/, found ${exeFiles.length}.`);
}

const blockmapFiles = fs
  .readdirSync(DIST_DIR)
  .filter((name) => name.endsWith('.exe.blockmap'));

if (blockmapFiles.length !== 1) {
  fail(`Expected exactly one .exe.blockmap artifact in dist/, found ${blockmapFiles.length}.`);
}

verifyUpdateManifest(exeFiles);

for (const exePath of exeFiles) {
  const stat = fs.statSync(exePath);
  if (stat.size === 0) {
    fail(`${path.basename(exePath)} is empty.`);
  }
  verifyPortableExecutable(exePath);
  verifyAuthenticodeSignature(exePath);
  log(`Verified installer ${path.basename(exePath)} (${Math.round(stat.size / 1024 / 1024)} MB).`);
}

log('Windows artifacts passed installer, Authenticode, and update manifest checks.');
