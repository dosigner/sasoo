const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execFileSync, spawnSync } = require('child_process');

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

function verifyUpdateManifest(zipFiles) {
  if (!fs.existsSync(UPDATE_FILE)) {
    fail(`latest-mac.yml not found at ${UPDATE_FILE}`);
  }

  const manifest = parseLatestMacYaml(UPDATE_FILE);
  const knownFiles = new Map();

  for (const filePath of zipFiles) {
    const stat = fs.statSync(filePath);
    knownFiles.set(path.basename(filePath), {
      path: filePath,
      size: stat.size,
      sha512: sha512Base64(filePath),
    });
  }

  if (manifest.files.length !== knownFiles.size) {
    fail(`latest-mac.yml lists ${manifest.files.length} files, but dist has ${knownFiles.size} mac ZIP artifacts.`);
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

function verifyJavaRuntime(appDir) {
  if (process.env.SASOO_SKIP_JAVA_BUNDLE === '1') {
    log('SASOO_SKIP_JAVA_BUNDLE=1 → skipping bundled Java runtime check.');
    return;
  }

  const runtimeRoot = path.join(
    appDir,
    'Contents',
    'Resources',
    'backend',
    'sasoo-backend',
    '_internal',
    'java-runtime'
  );
  const candidates = [
    path.join(runtimeRoot, 'bin', 'java'),
    path.join(runtimeRoot, 'Contents', 'Home', 'bin', 'java'),
  ];

  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    fail(`Bundled Java runtime not found. Checked:\n  ${candidates.join('\n  ')}`);
  }

  log(`Bundled Java runtime present: ${found}`);
}

function verifySignature(appDir) {
  const requireSigned = process.env.SASOO_REQUIRE_SIGNED === '1';

  // Identity check first: unsigned bundles and Electron's factory ad-hoc
  // signatures (Signature=adhoc, TeamIdentifier=not set) both count as
  // "no real signing identity", and --verify --deep --strict rejects them
  // with different messages, so string-matching the verify output is not
  // a reliable unsigned detector.
  const display = spawnSync('codesign', ['-dvv', appDir], { encoding: 'utf8' });
  if (display.error) {
    fail(`Failed to run codesign: ${display.error.message}`);
  }
  const displayOutput = `${display.stdout || ''}${display.stderr || ''}`;
  const hasIdentity =
    display.status === 0 &&
    !/Signature=adhoc/i.test(displayOutput) &&
    !/TeamIdentifier=not set/i.test(displayOutput);

  if (!hasIdentity) {
    if (requireSigned) {
      fail(
        `SASOO_REQUIRE_SIGNED=1 but the app has no signing identity:\n${displayOutput.trim()}`
      );
    }
    log('unsigned build (no signing identity) — signature checks skipped');
    return;
  }

  log(`Running codesign verification on ${path.basename(appDir)}`);
  const codesign = spawnSync(
    'codesign',
    ['--verify', '--deep', '--strict', '--verbose=2', appDir],
    { encoding: 'utf8' }
  );

  if (codesign.error) {
    fail(`Failed to run codesign: ${codesign.error.message}`);
  }

  if (codesign.status !== 0) {
    const codesignOutput = `${codesign.stdout || ''}${codesign.stderr || ''}`;
    fail(`codesign verification failed (exit ${codesign.status}):\n${codesignOutput.trim()}`);
  }

  log('codesign --verify --deep --strict passed.');

  const spctl = spawnSync('spctl', ['--assess', '--type', 'execute', '--verbose=2', appDir], {
    encoding: 'utf8',
  });
  if (spctl.error) {
    fail(`Failed to run spctl: ${spctl.error.message}`);
  }
  if (spctl.status !== 0) {
    fail(
      `spctl --assess --type execute failed (exit ${spctl.status}):\n${`${spctl.stdout || ''}${spctl.stderr || ''}`.trim()}`
    );
  }
  log('spctl --assess --type execute passed.');

  const stapler = spawnSync('xcrun', ['stapler', 'validate', appDir], { encoding: 'utf8' });
  if (stapler.error) {
    fail(`Failed to run xcrun stapler: ${stapler.error.message}`);
  }
  if (stapler.status !== 0) {
    fail(
      `xcrun stapler validate failed (exit ${stapler.status}):\n${`${stapler.stdout || ''}${stapler.stderr || ''}`.trim()}`
    );
  }
  log('xcrun stapler validate passed.');
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

    const appDir = appCandidates[0];
    verifyJavaRuntime(appDir);
    verifySignature(appDir);
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
