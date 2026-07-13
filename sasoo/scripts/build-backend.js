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

const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// Paths
const ROOT_DIR = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const SPEC_FILE = path.join(BACKEND_DIR, 'sasoo-backend.spec');
const OUTPUT_DIR = path.join(BACKEND_DIR, 'dist', 'sasoo-backend');
const BUILD_CACHE_DIR = path.join(BACKEND_DIR, '.build-cache');
const PYINSTALLER_CACHE_DIR = path.join(BUILD_CACHE_DIR, 'pyinstaller');
const MPLCONFIGDIR = path.join(BUILD_CACHE_DIR, 'matplotlib');

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

  error(`PyInstaller not found for Python: ${pythonPath}`);
  if (pythonPath.includes('.venv')) {
    error(`Install it in the backend virtual environment: "${pythonPath}" -m pip install pyinstaller`);
  } else {
    error('Install it with: python3 -m pip install pyinstaller');
    warn('Tip: create backend/.venv first so macOS builds use a predictable interpreter.');
  }
  return false;
}

/**
 * Inspect the Python version used for packaging.
 * Release packaging is validated on Python 3.12 in CI.
 */
function inspectPythonVersion(pythonPath) {
  info('Inspecting Python runtime...');

  try {
    const result = spawnSync(
      pythonPath,
      ['-c', 'import platform; print(platform.python_version())'],
      {
        encoding: 'utf-8',
        stdio: 'pipe',
      }
    );

    if (result.status !== 0) {
      warn('Could not determine Python version. Continuing without a release-version check.');
      return;
    }

    const version = result.stdout.trim();
    const [major, minor] = version.split('.').map((part) => Number(part));
    info(`Python version: ${version}`);

    if (major === 3 && minor === 12) {
      success('Python 3.12 detected. This matches the CI release packaging baseline.');
      return;
    }

    warn(
      `Python ${version} detected. Local builds can still run, but release-quality packaging is only validated on Python 3.12.`
    );
  } catch (e) {
    warn('Could not determine Python version. Continuing without a release-version check.');
  }
}

/**
 * Detect platform-specific files that should never ship in the current build.
 */
function findForeignArtifacts(rootDir) {
  const markersByPlatform = {
    darwin: [/\.exe$/i, /\.dll$/i, /\.pyd$/i, /win_amd64/i, /win32/i],
    linux: [/\.exe$/i, /\.dll$/i, /\.pyd$/i, /win_amd64/i, /\.dylib$/i, /darwin/i],
    win32: [/\.so$/i, /\.dylib$/i, /darwin/i],
  };

  const markers = markersByPlatform[process.platform] ?? [];
  const matches = [];

  function walkDir(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walkDir(fullPath);
        continue;
      }

      const relativePath = path.relative(rootDir, fullPath);
      const normalizedRelativePath = relativePath.replace(/\\/g, '/');
      // Ignore IANA timezone names like ".../tzdata/.../Darwin" on non-mac builds.
      if (
        /(^|\/)tzdata(\/|$)/i.test(normalizedRelativePath) &&
        /\/Darwin$/i.test(normalizedRelativePath)
      ) {
        continue;
      }
      if (markers.some((pattern) => pattern.test(relativePath))) {
        matches.push(relativePath);
      }
    }
  }

  walkDir(rootDir);
  return matches;
}

function javaExecutableNameForPlatform(platform = process.platform) {
  return platform === 'win32' ? 'java.exe' : 'java';
}

function hasPlatformJavaExecutable(javaHomePath) {
  if (!javaHomePath) {
    return false;
  }

  const candidates = [
    path.join(javaHomePath, 'bin', javaExecutableNameForPlatform()),
    path.join(javaHomePath, 'Contents', 'Home', 'bin', javaExecutableNameForPlatform()),
  ];

  return candidates.some((candidate) => fs.existsSync(candidate));
}

/**
 * Ensure a platform Java runtime is available for bundling before PyInstaller
 * runs. Injects SASOO_BUNDLED_JAVA_HOME so the spec collects it into the build.
 *
 * Resolution order:
 *   1. Committed backend/java-runtime that matches this platform -> no download
 *      (the macOS arm64 case; download count stays 0).
 *   2. SASOO_SKIP_JAVA_BUNDLE=1 -> skip (production ODL Java mode needs system Java).
 *   3. Otherwise download+cache via scripts/ensure-java-runtime.js.
 */
async function ensureJavaForBundle() {
  info('Ensuring bundled Java runtime for OpenDataLoader...');

  const committedRuntime = path.join(BACKEND_DIR, 'java-runtime');
  if (fs.existsSync(committedRuntime) && hasPlatformJavaExecutable(committedRuntime)) {
    success(
      `Committed JRE matches ${process.platform}/${process.arch} -> download skip (${committedRuntime}).`
    );
    return;
  }

  if (process.env.SASOO_SKIP_JAVA_BUNDLE === '1') {
    warn(
      'SASOO_SKIP_JAVA_BUNDLE=1 -> skipping JRE provisioning. ' +
      'Production ODL Java mode will require system Java on this platform.'
    );
    return;
  }

  const { ensureJavaRuntime, JRE_RELEASE_NAME } = require('./ensure-java-runtime');
  const result = await ensureJavaRuntime({
    platform: process.platform,
    arch: process.arch,
    cacheDir: path.join(BACKEND_DIR, '.jre-cache'),
    releaseName: JRE_RELEASE_NAME,
  });
  process.env.SASOO_BUNDLED_JAVA_HOME = result.javaHome;
  success(
    `Provisioned JRE for bundle: ${result.javaHome} (semver ${result.semver}, source ${result.source}).`
  );
  info('SASOO_BUNDLED_JAVA_HOME injected for the PyInstaller spec.');
}

function resolveBundledJavaRuntimeSource() {
  const candidates = [
    { label: 'backend/java-runtime', dir: path.join(BACKEND_DIR, 'java-runtime') },
    { label: 'SASOO_BUNDLED_JAVA_HOME', dir: process.env.SASOO_BUNDLED_JAVA_HOME },
    { label: 'JAVA_HOME', dir: process.env.JAVA_HOME },
  ];

  const mismatched = [];
  for (const candidate of candidates) {
    if (!candidate.dir || !fs.existsSync(candidate.dir)) {
      continue;
    }
    if (hasPlatformJavaExecutable(candidate.dir)) {
      return { ...candidate, mismatched };
    }
    mismatched.push(candidate.label);
  }

  return { label: null, dir: null, mismatched };
}

/**
 * Clean previous build artifacts.
 */
function cleanBuild() {
  info('Cleaning previous build...');

  const dirsToClean = [
    path.join(BACKEND_DIR, 'dist'),
    path.join(BACKEND_DIR, 'build'),
    BUILD_CACHE_DIR,
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

  fs.mkdirSync(PYINSTALLER_CACHE_DIR, { recursive: true });
  fs.mkdirSync(MPLCONFIGDIR, { recursive: true });

  const args = [
    '-m', 'PyInstaller',
    '--clean',
    '--noconfirm',
    SPEC_FILE,
  ];

  info(`Command: ${pythonPath} ${args.join(' ')}`);

  // spawnSync(배열 인자, 셸 미경유): 한글 리포지터리 경로(예: "논문_사수_개발중")나
  // 공백이 든 경로에서 셸 인용/코드페이지 문제 없이 SPEC_FILE·pythonPath를 그대로 전달한다.
  // PYTHONUTF8=1: 비(非)한국어 로케일 Windows에서도 한글 경로 처리를 UTF-8로 고정한다.
  const result = spawnSync(pythonPath, args, {
    cwd: BACKEND_DIR,
    stdio: 'inherit',
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1',
      PYINSTALLER_CONFIG_DIR: PYINSTALLER_CACHE_DIR,
      MPLCONFIGDIR,
    },
  });

  if (result.error) {
    error(`PyInstaller failed: ${result.error.message}`);
    return false;
  }
  if (result.status !== 0) {
    error(`PyInstaller exited with code ${result.status}`);
    return false;
  }
  return true;
}

/**
 * Verify the build output.
 */
function verifyBuild() {
  info('Verifying build output...');

  const exePath = path.join(OUTPUT_DIR, process.platform === 'win32' ? 'sasoo-backend.exe' : 'sasoo-backend');
  const odlJarPath = path.join(
    OUTPUT_DIR,
    '_internal',
    'opendataloader_pdf',
    'jar',
    'opendataloader-pdf-cli.jar'
  );

  if (!fs.existsSync(exePath)) {
    error(`Executable not found: ${exePath}`);
    return false;
  }
  if (!fs.existsSync(odlJarPath)) {
    error(`OpenDataLoader JAR not found in build output: ${odlJarPath}`);
    return false;
  }

  const stats = fs.statSync(exePath);
  const sizeMB = (stats.size / 1024 / 1024).toFixed(2);

  success(`Executable created: ${exePath}`);
  info(`Size: ${sizeMB} MB`);
  info(`OpenDataLoader JAR found: ${odlJarPath}`);

  // Informational: which source the spec drew the runtime from (if any).
  const bundledJavaRuntime = resolveBundledJavaRuntimeSource();
  if (bundledJavaRuntime.dir) {
    info(`Bundled Java runtime source: ${bundledJavaRuntime.label} (${bundledJavaRuntime.dir})`);
  } else if (bundledJavaRuntime.mismatched.length > 0) {
    info(
      `Java runtime source candidates present but platform-mismatched: ${bundledJavaRuntime.mismatched.join(', ')}.`
    );
  } else {
    info('No committed/env Java runtime source matched; relying on provisioned cache if any.');
  }

  // Hard gate: the packaged bundle must actually contain a platform Java
  // executable, otherwise the ODL default engine breaks at runtime.
  const javaExe = process.platform === 'win32' ? 'java.exe' : 'java';
  const bundledJavaCandidates = [
    path.join(OUTPUT_DIR, '_internal', 'java-runtime', 'bin', javaExe),
    path.join(OUTPUT_DIR, '_internal', 'java-runtime', 'Contents', 'Home', 'bin', javaExe),
  ];
  const bundledJavaFound = bundledJavaCandidates.find((candidate) => fs.existsSync(candidate));
  if (bundledJavaFound) {
    success(`Bundled Java runtime present in build output: ${bundledJavaFound}`);
  } else if (process.env.SASOO_SKIP_JAVA_BUNDLE === '1') {
    warn(
      'No bundled Java runtime in build output, but SASOO_SKIP_JAVA_BUNDLE=1 is set. ' +
      'Production ODL Java mode will require system Java.'
    );
  } else {
    error(
      'Bundled Java runtime missing from build output (_internal/java-runtime/bin). ' +
      'The ODL default PDF engine would fail at runtime.'
    );
    error('Set SASOO_SKIP_JAVA_BUNDLE=1 to bypass intentionally, or ensure JRE provisioning succeeds.');
    return false;
  }

  const foreignArtifacts = findForeignArtifacts(OUTPUT_DIR);
  if (foreignArtifacts.length > 0) {
    error('Platform-mismatched backend artifacts detected in build output:');
    for (const artifact of foreignArtifacts.slice(0, 10)) {
      console.log(`  - ${artifact}`);
    }
    if (foreignArtifacts.length > 10) {
      console.log(`  ... and ${foreignArtifacts.length - 10} more`);
    }
    error('Clean the backend build output and rebuild on the target platform.');
    return false;
  }

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

  inspectPythonVersion(pythonPath);

  // Clean previous build
  cleanBuild();

  // Ensure a platform Java runtime is available/injected before packaging.
  console.log('');
  try {
    await ensureJavaForBundle();
  } catch (e) {
    error(`Java runtime provisioning failed: ${e.message}`);
    process.exit(1);
  }

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
