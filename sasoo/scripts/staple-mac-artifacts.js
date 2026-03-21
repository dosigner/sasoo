const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT_DIR = path.resolve(__dirname, '..');
const DIST_DIR = path.join(ROOT_DIR, 'dist');

function fail(message) {
  console.error(`[staple-mac-artifacts] ${message}`);
  process.exit(1);
}

function log(message) {
  console.log(`[staple-mac-artifacts] ${message}`);
}

function run(command, args) {
  execFileSync(command, args, { stdio: 'inherit' });
}

if (process.platform !== 'darwin') {
  fail(`Stapling is only supported on macOS. Current platform: ${process.platform}`);
}

if (!fs.existsSync(DIST_DIR)) {
  fail(`dist directory not found: ${DIST_DIR}`);
}

const distEntries = fs.readdirSync(DIST_DIR, { withFileTypes: true });
const appBundles = [];
const dmgFiles = [];

for (const entry of distEntries) {
  const fullPath = path.join(DIST_DIR, entry.name);

  if (entry.isDirectory() && entry.name.startsWith('mac')) {
    const nested = fs.readdirSync(fullPath, { withFileTypes: true });
    for (const nestedEntry of nested) {
      if (nestedEntry.isDirectory() && nestedEntry.name.endsWith('.app')) {
        appBundles.push(path.join(fullPath, nestedEntry.name));
      }
    }
  }

  if (entry.isFile() && entry.name.endsWith('.dmg')) {
    dmgFiles.push(fullPath);
  }
}

if (appBundles.length === 0) {
  fail('No macOS app bundles found in dist/. Build the app before stapling.');
}

for (const appPath of appBundles) {
  log(`Stapling ${path.relative(ROOT_DIR, appPath)}`);
  run('xcrun', ['stapler', 'staple', '-v', appPath]);
  run('xcrun', ['stapler', 'validate', '-v', appPath]);
}

for (const dmgPath of dmgFiles) {
  log(`Stapling ${path.relative(ROOT_DIR, dmgPath)}`);
  run('xcrun', ['stapler', 'staple', '-v', dmgPath]);
  run('xcrun', ['stapler', 'validate', '-v', dmgPath]);
}

log('Stapling completed successfully.');
