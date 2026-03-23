const fs = require('fs');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const OUTPUT_DIRS = [
  path.join(ROOT_DIR, 'dist'),
  path.join(ROOT_DIR, 'dist-electron'),
  path.join(ROOT_DIR, 'frontend', 'dist'),
  path.join(ROOT_DIR, 'backend', 'dist'),
  path.join(ROOT_DIR, 'backend', 'build'),
  path.join(ROOT_DIR, 'backend', '.build-cache'),
];

function fail(message) {
  console.error(`[prepare-win-build] ${message}`);
  process.exit(1);
}

function log(message) {
  console.log(`[prepare-win-build] ${message}`);
}

if (process.platform !== 'win32') {
  fail(`Windows builds must run on Windows. Current platform: ${process.platform}`);
}

for (const dir of OUTPUT_DIRS) {
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
    log(`Removed ${path.relative(ROOT_DIR, dir)}`);
  }
}

log('Windows build directories are clean.');
