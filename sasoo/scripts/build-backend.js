/**
 * Sasoo Backend Build Script
 *
 * Builds the Python backend into a standalone executable using PyInstaller.
 *
 * Usage:
 *   node scripts/build-backend.js
 *
 * Requirements:
 *   - Python 3.10+ with PyInstaller installed
 *   - Virtual environment at backend/.venv (recommended)
 */

const { execSync, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// Paths
const ROOT_DIR = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const SPEC_FILE = path.join(BACKEND_DIR, 'sasoo-backend.spec');
const OUTPUT_DIR = path.join(BACKEND_DIR, 'dist', 'sasoo-backend');

// Colors for console output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
};

function log(message, color = colors.reset) {
  console.log(`${color}[build-backend] ${message}${colors.reset}`);
}

function error(message) {
  log(message, colors.red);
}

function success(message) {
  log(message, colors.green);
}

function info(message) {
  log(message, colors.cyan);
}

function warn(message) {
  log(message, colors.yellow);
}

/**
 * Find Python executable in virtual environment or system.
 */
function findPython() {
  const venvPaths = [
    path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe'),
    path.join(BACKEND_DIR, '.venv', 'bin', 'python'),
    path.join(BACKEND_DIR, 'venv', 'Scripts', 'python.exe'),
    path.join(BACKEND_DIR, 'venv', 'bin', 'python'),
  ];

  for (const venvPath of venvPaths) {
    if (fs.existsSync(venvPath)) {
      info(`Found Python at: ${venvPath}`);
      return venvPath;
    }
  }

  // Fall back to system Python
  warn('No virtual environment found, using system Python');
  return process.platform === 'win32' ? 'python' : 'python3';
}

/**
 * Check if PyInstaller is installed.
 */
function checkPyInstaller(pythonPath) {
  info('Checking PyInstaller installation...');

  try {
    const result = spawnSync(pythonPath, ['-m', 'PyInstaller', '--version'], {
      encoding: 'utf-8',
      stdio: 'pipe',
    });

    if (result.status === 0) {
      success(`PyInstaller version: ${result.stdout.trim()}`);
      return true;
    }
  } catch (e) {
    // PyInstaller not found
  }

  error('PyInstaller not found. Install it with: pip install pyinstaller');
  return false;
}

/**
 * Clean previous build artifacts.
 */
function cleanBuild() {
  info('Cleaning previous build...');

  const dirsToClean = [
    path.join(BACKEND_DIR, 'dist'),
    path.join(BACKEND_DIR, 'build'),
  ];

  for (const dir of dirsToClean) {
    if (fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
      info(`Removed: ${dir}`);
    }
  }
}

/**
 * Run PyInstaller to build the backend.
 */
function runPyInstaller(pythonPath) {
  info('Running PyInstaller...');
  info(`Spec file: ${SPEC_FILE}`);

  const args = [
    '-m', 'PyInstaller',
    '--clean',
    '--noconfirm',
    SPEC_FILE,
  ];

  info(`Command: ${pythonPath} ${args.join(' ')}`);

  try {
    execSync(`"${pythonPath}" ${args.join(' ')}`, {
      cwd: BACKEND_DIR,
      stdio: 'inherit',
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
      },
    });

    return true;
  } catch (e) {
    error(`PyInstaller failed: ${e.message}`);
    return false;
  }
}

/**
 * Verify the build output.
 */
function verifyBuild() {
  info('Verifying build output...');

  const exePath = path.join(OUTPUT_DIR, process.platform === 'win32' ? 'sasoo-backend.exe' : 'sasoo-backend');

  if (!fs.existsSync(exePath)) {
    error(`Executable not found: ${exePath}`);
    return false;
  }

  const stats = fs.statSync(exePath);
  const sizeMB = (stats.size / 1024 / 1024).toFixed(2);

  success(`Executable created: ${exePath}`);
  info(`Size: ${sizeMB} MB`);

  // List the output directory contents
  info('Output directory contents:');
  const files = fs.readdirSync(OUTPUT_DIR);
  for (const file of files.slice(0, 10)) {
    const filePath = path.join(OUTPUT_DIR, file);
    const fileStats = fs.statSync(filePath);
    const isDir = fileStats.isDirectory();
    console.log(`  ${isDir ? '[DIR]' : '     '} ${file}`);
  }
  if (files.length > 10) {
    console.log(`  ... and ${files.length - 10} more files`);
  }

  return true;
}

/**
 * Calculate total build size.
 */
function calculateBuildSize() {
  if (!fs.existsSync(OUTPUT_DIR)) return;

  let totalSize = 0;

  function walkDir(dir) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const filePath = path.join(dir, file);
      const stats = fs.statSync(filePath);
      if (stats.isDirectory()) {
        walkDir(filePath);
      } else {
        totalSize += stats.size;
      }
    }
  }

  walkDir(OUTPUT_DIR);

  const sizeMB = (totalSize / 1024 / 1024).toFixed(2);
  info(`Total build size: ${sizeMB} MB`);
}

/**
 * Main build process.
 */
async function main() {
  console.log('');
  log('='.repeat(60));
  log('Sasoo Backend Build');
  log('='.repeat(60));
  console.log('');

  // Check spec file exists
  if (!fs.existsSync(SPEC_FILE)) {
    error(`Spec file not found: ${SPEC_FILE}`);
    process.exit(1);
  }

  // Find Python
  const pythonPath = findPython();

  // Check PyInstaller
  if (!checkPyInstaller(pythonPath)) {
    process.exit(1);
  }

  // Clean previous build
  cleanBuild();

  // Run PyInstaller
  console.log('');
  if (!runPyInstaller(pythonPath)) {
    error('Build failed!');
    process.exit(1);
  }

  console.log('');

  // Verify build
  if (!verifyBuild()) {
    error('Build verification failed!');
    process.exit(1);
  }

  // Calculate size
  calculateBuildSize();

  console.log('');
  success('='.repeat(60));
  success('Build completed successfully!');
  success('='.repeat(60));
  console.log('');
  info(`Output: ${OUTPUT_DIR}`);
  console.log('');
}

main().catch((e) => {
  error(`Unexpected error: ${e.message}`);
  process.exit(1);
});
