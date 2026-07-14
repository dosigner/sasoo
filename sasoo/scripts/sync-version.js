#!/usr/bin/env node
/**
 * Sync version from root VERSION file to all package.json files and backend.
 *
 * Usage: node scripts/sync-version.js
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const VERSION_FILE = path.join(ROOT, 'VERSION');

// Read version
const version = fs.readFileSync(VERSION_FILE, 'utf-8').trim();
if (!/^\d+\.\d+\.\d+/.test(version)) {
  console.error(`Invalid version in VERSION file: "${version}"`);
  process.exit(1);
}

console.log(`Syncing version: ${version}`);

// Files to update
const packageJsonFiles = [
  path.join(ROOT, 'package.json'),
  path.join(ROOT, 'frontend', 'package.json'),
];

let updated = 0;

for (const filePath of packageJsonFiles) {
  if (!fs.existsSync(filePath)) {
    console.warn(`  SKIP ${path.relative(ROOT, filePath)} (not found)`);
    continue;
  }

  const pkg = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  if (pkg.version !== version) {
    const old = pkg.version;
    pkg.version = version;
    fs.writeFileSync(filePath, JSON.stringify(pkg, null, 2) + '\n', 'utf-8');
    console.log(`  ${path.relative(ROOT, filePath)}: ${old} -> ${version}`);
    updated++;
  } else {
    console.log(`  ${path.relative(ROOT, filePath)}: already ${version}`);
  }
}

// Update backend main.py version string
const mainPy = path.join(ROOT, 'backend', 'main.py');
if (fs.existsSync(mainPy)) {
  let content = fs.readFileSync(mainPy, 'utf-8');
  const constructorVersionPattern = /version="[\d.]+"/g;
  const responseVersionPattern = /("version":\s*)"[\d.]+"/g;
  const newContent = content
    .replace(constructorVersionPattern, `version="${version}"`)
    .replace(responseVersionPattern, `$1"${version}"`);
  if (newContent !== content) {
    fs.writeFileSync(mainPy, newContent, 'utf-8');
    console.log(`  backend/main.py: version strings updated to ${version}`);
    updated++;
  } else {
    console.log(`  backend/main.py: already ${version}`);
  }
}

console.log(`\nDone. ${updated} file(s) updated.`);
