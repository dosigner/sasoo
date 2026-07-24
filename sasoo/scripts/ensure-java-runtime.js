/**
 * Sasoo JRE Auto-Provisioning
 *
 * Downloads and caches an Eclipse Temurin JRE for the OpenDataLoader (ODL)
 * default PDF text engine, which requires a Java runtime. The repository only
 * commits a macOS arm64 JRE (backend/java-runtime, flat layout); this script
 * fills the gap for other platforms (notably Windows x64) at build time.
 *
 * Zero external dependencies: Node 20 built-in fetch, CommonJS. The resolved
 * java_home is meant to be injected into PyInstaller via SASOO_BUNDLED_JAVA_HOME
 * (see backend/sasoo-backend.spec:_find_java_runtime_source), which rglobs the
 * java_home relative to itself, so java_home must be the directory that DIRECTLY
 * contains bin/java(.exe) to yield a flat `_internal/java-runtime/bin/...`.
 *
 * Usage:
 *   node scripts/ensure-java-runtime.js [--os windows] [--arch x64] \
 *        [--cache-dir <dir>] [--release <name>] [--force] [--check]
 *
 * --os/--arch override the current platform (e.g. simulate the Windows path on
 * macOS). --check prints cache status without downloading.
 */

const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { Readable } = require('stream');
const { pipeline } = require('stream/promises');

// ---------------------------------------------------------------------------
// Pinned JRE release.
//
// Kept identical to the committed macOS JRE build (backend/java-runtime,
// Temurin 21.0.10+7). When upgrading the bundled Java runtime, replace BOTH
// this constant AND the committed backend/java-runtime JRE together so every
// platform ships the same build. Set SASOO_JRE_RELEASE to override ad hoc, or
// SASOO_JRE_CHANNEL=latest to track the latest Temurin 21 build instead.
// ---------------------------------------------------------------------------
const JRE_RELEASE_NAME = process.env.SASOO_JRE_RELEASE || 'jdk-21.0.10+7';

const ROOT_DIR = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const DEFAULT_CACHE_DIR = path.join(BACKEND_DIR, '.jre-cache');

const ADOPTIUM_API = 'https://api.adoptium.net';

// Console colors (aligned with scripts/build-backend.js conventions).
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
};

function log(message, color = colors.reset) {
  console.log(`${color}[ensure-java-runtime] ${message}${colors.reset}`);
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
 * Normalize a user-provided or Node platform string to a Node-style platform.
 */
function normalizePlatform(value) {
  const s = String(value).toLowerCase();
  if (['win32', 'windows', 'win'].includes(s)) return 'win32';
  if (['darwin', 'mac', 'macos', 'osx'].includes(s)) return 'darwin';
  if (s === 'linux') return 'linux';
  return s;
}

/**
 * Normalize a user-provided or Node arch string to a Node-style arch.
 */
function normalizeArch(value) {
  const s = String(value).toLowerCase();
  if (['x64', 'amd64', 'x86_64'].includes(s)) return 'x64';
  if (['arm64', 'aarch64'].includes(s)) return 'arm64';
  return s;
}

/**
 * Map a Node platform/arch pair to the Adoptium download target.
 */
function resolveTarget(platform, arch) {
  const key = `${platform}/${arch}`;
  const table = {
    'win32/x64': { os: 'windows', arch: 'x64', ext: '.zip' },
    'darwin/arm64': { os: 'mac', arch: 'aarch64', ext: '.tar.gz' },
    'darwin/x64': { os: 'mac', arch: 'x64', ext: '.tar.gz' },
    'linux/x64': { os: 'linux', arch: 'x64', ext: '.tar.gz' },
  };
  const target = table[key];
  if (!target) {
    throw new Error(`지원하지 않는 플랫폼/아키텍처 조합: ${key}`);
  }
  return target;
}

function javaExecutableName(targetOs) {
  return targetOs === 'windows' ? 'java.exe' : 'java';
}

/**
 * Fetch and parse JSON, converting network failures into an actionable error.
 */
async function fetchJson(url) {
  let res;
  try {
    res = await fetch(url, { headers: { accept: 'application/json' } });
  } catch (e) {
    throw new Error(
      `Adoptium 메타 조회 네트워크 실패: ${e.message}. ` +
      '인터넷 접근 불가. SASOO_SKIP_JAVA_BUNDLE=1로 스킵하거나 backend/java-runtime에 매칭 JRE를 배치하세요.'
    );
  }
  if (!res.ok) {
    throw new Error(`Adoptium 메타 조회 실패: HTTP ${res.status} ${res.statusText} (${url})`);
  }
  return res.json();
}

/**
 * Resolve download metadata (link, sha256 checksum, filename, semver) for the
 * requested release. Supports both the pinned release_name channel and the
 * rolling latest/21 channel.
 */
async function fetchReleaseMeta(releaseName, os, arch, channel) {
  if (channel === 'latest') {
    const url =
      `${ADOPTIUM_API}/v3/assets/latest/21/hotspot` +
      `?architecture=${arch}&image_type=jre&os=${os}&vendor=eclipse`;
    info(`Querying Adoptium latest channel: ${url}`);
    const json = await fetchJson(url);
    const asset = Array.isArray(json) ? json[0] : json;
    const pkg = asset && asset.binary && asset.binary.package;
    if (!pkg || !pkg.link) {
      throw new Error(`Adoptium latest 채널 응답에 유효한 바이너리가 없음 (os=${os}, arch=${arch}).`);
    }
    return {
      link: pkg.link,
      checksum: pkg.checksum,
      name: pkg.name,
      semver: asset.version && asset.version.semver,
      releaseName: asset.release_name || releaseName,
    };
  }

  const url =
    `${ADOPTIUM_API}/v3/assets/release_name/eclipse/${encodeURIComponent(releaseName)}` +
    `?architecture=${arch}&image_type=jre&os=${os}&jvm_impl=hotspot&project=jdk`;
  info(`Querying Adoptium release: ${url}`);
  const json = await fetchJson(url);
  const release = Array.isArray(json) ? json[0] : json;
  const binary = release && Array.isArray(release.binaries) ? release.binaries[0] : null;
  const pkg = binary && binary.package;
  if (!pkg || !pkg.link) {
    throw new Error(
      `Adoptium 응답에 유효한 바이너리가 없음 (release=${releaseName}, os=${os}, arch=${arch}). ` +
      '릴리스명/플랫폼 조합을 확인하세요.'
    );
  }
  return {
    link: pkg.link,
    checksum: pkg.checksum,
    name: pkg.name,
    semver: release.version_data && release.version_data.semver,
    releaseName,
  };
}

/**
 * Download a single file to destPart via streaming.
 */
async function downloadOnce(url, destPart) {
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status} ${res.statusText}`);
  }
  await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(destPart));
}

/**
 * Download with a single retry. Removes the partial file on failure.
 */
async function downloadWithRetry(url, destPart, { retries = 1 } = {}) {
  let attempt = 0;
  // eslint-disable-next-line no-constant-condition
  for (;;) {
    try {
      await downloadOnce(url, destPart);
      return;
    } catch (e) {
      try {
        fs.rmSync(destPart, { force: true });
      } catch (_) {
        // ignore cleanup failure
      }
      if (attempt >= retries) {
        throw new Error(
          `다운로드 실패(${attempt + 1}회 시도): ${e.message}. ` +
          '인터넷 접근 불가면 SASOO_SKIP_JAVA_BUNDLE=1로 스킵하거나 backend/java-runtime에 매칭 JRE를 배치하세요.'
        );
      }
      attempt += 1;
      warn(`다운로드 재시도 ${attempt}/${retries}: ${e.message}`);
    }
  }
}

/**
 * Stream a SHA-256 hash of a file and compare against the expected hex digest.
 */
function verifySha256(filePath, expectedHex) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => {
      const actual = hash.digest('hex').toLowerCase();
      resolve(actual === String(expectedHex || '').toLowerCase());
    });
  });
}

/**
 * Extract a .tar.gz or .zip archive using bsdtar (macOS default, Windows 10
 * 1803+ default). Falls back to PowerShell Expand-Archive on Windows if bsdtar
 * cannot handle the zip.
 */
function extractArchive(archivePath, destDir, ext) {
  const isZip = ext === '.zip';
  const args = isZip
    ? ['-xf', archivePath, '-C', destDir]
    : ['-xzf', archivePath, '-C', destDir];
  info(`Extracting: tar ${args.join(' ')}`);
  const result = spawnSync('tar', args, { stdio: 'inherit' });
  if (result.status === 0) {
    return;
  }

  if (isZip && process.platform === 'win32') {
    warn('bsdtar zip 해제 실패 → PowerShell Expand-Archive 폴백');
    const ps = spawnSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        `Expand-Archive -Path "${archivePath}" -DestinationPath "${destDir}" -Force`,
      ],
      { stdio: 'inherit' }
    );
    if (ps.status === 0) {
      return;
    }
    throw new Error(`zip 해제 실패 (tar + PowerShell Expand-Archive): status ${ps.status}`);
  }

  const detail = result.error ? `: ${result.error.message}` : '';
  throw new Error(`아카이브 해제 실패: tar status ${result.status}${detail}`);
}

/**
 * Locate the java_home inside an extracted tree.
 *
 * Returns the directory that DIRECTLY contains bin/java(.exe) — for Windows zip
 * this is `<root>/jdk-...-jre`, for macOS tar.gz it is
 * `<root>/jdk-...-jre/Contents/Home`. This exact selection makes the value a
 * valid SASOO_BUNDLED_JAVA_HOME so the PyInstaller spec produces a flat
 * `_internal/java-runtime/bin/...` layout.
 */
function findJavaHome(extractRoot, targetOs) {
  const execName = javaExecutableName(targetOs);

  const candidateRoots = [extractRoot];
  try {
    for (const entry of fs.readdirSync(extractRoot, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        candidateRoots.push(path.join(extractRoot, entry.name));
      }
    }
  } catch (_) {
    // extractRoot unreadable -> handled by null return below
  }

  for (const dir of candidateRoots) {
    if (fs.existsSync(path.join(dir, 'bin', execName))) {
      return dir;
    }
    const macHome = path.join(dir, 'Contents', 'Home');
    if (fs.existsSync(path.join(macHome, 'bin', execName))) {
      return macHome;
    }
  }

  return null;
}

/**
 * Read the JRE version from a Temurin `release` file. Prefers SEMANTIC_VERSION
 * (e.g. 21.0.10+7), falls back to JAVA_VERSION (e.g. 21.0.10).
 */
function readReleaseVersion(releaseFilePath) {
  if (!fs.existsSync(releaseFilePath)) {
    return { semantic: null, java: null };
  }
  const text = fs.readFileSync(releaseFilePath, 'utf8');
  const semantic = text.match(/^SEMANTIC_VERSION="?([^"\r\n]+)"?/m);
  const java = text.match(/^JAVA_VERSION="?([^"\r\n]+)"?/m);
  return {
    semantic: semantic ? semantic[1] : null,
    java: java ? java[1] : null,
  };
}

function baseVersion(semver) {
  // "21.0.10+7" / "21.0.10-LTS" -> "21.0.10"
  return String(semver || '').replace(/[-+].*$/, '');
}

/**
 * Canonicalize a version to "major.minor.patch+build" using the leading numeric
 * build token after '+'. Reconciles the Adoptium API semver (e.g.
 * "21.0.10+7.0.LTS") with the on-disk `release` file SEMANTIC_VERSION
 * (e.g. "21.0.10+7"), which carry different suffixes for the same build.
 */
function canonicalVersion(semver) {
  const s = String(semver || '');
  const base = baseVersion(s);
  const plusIndex = s.indexOf('+');
  if (plusIndex === -1) {
    return base;
  }
  const buildMatch = s.slice(plusIndex + 1).match(/^\d+/);
  return buildMatch ? `${base}+${buildMatch[0]}` : base;
}

/**
 * Validate an existing cache: resolved.json present, java executable present,
 * and the release file version matches the recorded semver.
 */
function readCacheIfValid(platformCacheDir, resolvedJsonPath, releaseName, channel, target) {
  if (!fs.existsSync(resolvedJsonPath)) {
    return null;
  }

  let resolved;
  try {
    resolved = JSON.parse(fs.readFileSync(resolvedJsonPath, 'utf8'));
  } catch (_) {
    return null;
  }

  // On the pinned channel, a different recorded release invalidates the cache.
  if (channel !== 'latest' && resolved.releaseName && resolved.releaseName !== releaseName) {
    return null;
  }

  if (!resolved.javaHome) {
    return null;
  }
  const javaHomeAbs = path.join(platformCacheDir, resolved.javaHome);
  const execName = javaExecutableName(target.os);
  if (!fs.existsSync(path.join(javaHomeAbs, 'bin', execName))) {
    return null;
  }

  // Version consistency check against the on-disk release file.
  const version = readReleaseVersion(path.join(javaHomeAbs, 'release'));
  const expected = resolved.semver;
  if (expected) {
    if (version.semantic) {
      if (canonicalVersion(version.semantic) !== canonicalVersion(expected)) {
        return null;
      }
    } else if (version.java) {
      if (baseVersion(version.java) !== baseVersion(expected)) {
        return null;
      }
    }
  }

  return { javaHome: javaHomeAbs, semver: resolved.semver };
}

/**
 * Ensure a platform JRE is present in the cache and return its java_home.
 *
 * @returns {Promise<{javaHome: string, semver: string, source: 'cache'|'download'}>}
 */
async function ensureJavaRuntime({ platform, arch, cacheDir, releaseName, channel, force } = {}) {
  const normPlatform = normalizePlatform(platform || process.platform);
  const normArch = normalizeArch(arch || process.arch);
  const target = resolveTarget(normPlatform, normArch);
  const effectiveRelease = releaseName || JRE_RELEASE_NAME;
  const effectiveChannel = channel || (process.env.SASOO_JRE_CHANNEL === 'latest' ? 'latest' : 'release');
  const effectiveCacheDir = cacheDir || DEFAULT_CACHE_DIR;

  const platformCacheDir = path.join(effectiveCacheDir, `${target.os}-${target.arch}`);
  const resolvedJsonPath = path.join(platformCacheDir, 'resolved.json');

  if (!force) {
    const cached = readCacheIfValid(platformCacheDir, resolvedJsonPath, effectiveRelease, effectiveChannel, target);
    if (cached) {
      success(`Cache hit: ${cached.javaHome} (semver ${cached.semver}) — download skip.`);
      return { javaHome: cached.javaHome, semver: cached.semver, source: 'cache' };
    }
  }

  info(`Provisioning JRE for ${target.os}/${target.arch} (release ${effectiveRelease}, channel ${effectiveChannel}).`);
  const meta = await fetchReleaseMeta(effectiveRelease, target.os, target.arch, effectiveChannel);
  info(`Resolved package: ${meta.name} (semver ${meta.semver}).`);

  // Fresh working directory to avoid stale extraction.
  fs.rmSync(platformCacheDir, { recursive: true, force: true });
  fs.mkdirSync(platformCacheDir, { recursive: true });

  const archivePath = path.join(platformCacheDir, meta.name);
  const partPath = `${archivePath}.part`;

  info(`Downloading: ${meta.link}`);
  await downloadWithRetry(meta.link, partPath, { retries: 1 });

  let checksumOk = await verifySha256(partPath, meta.checksum);
  if (!checksumOk) {
    warn('sha256 불일치 — 공급망 경고. 파일 삭제 후 1회 재다운로드합니다.');
    fs.rmSync(partPath, { force: true });
    await downloadWithRetry(meta.link, partPath, { retries: 1 });
    checksumOk = await verifySha256(partPath, meta.checksum);
    if (!checksumOk) {
      fs.rmSync(platformCacheDir, { recursive: true, force: true });
      throw new Error(
        'sha256 검증 실패 (공급망 경고): 다운로드 파일 해시가 Adoptium 메타와 일치하지 않습니다.'
      );
    }
  }
  success('sha256 검증 통과.');

  fs.renameSync(partPath, archivePath);
  extractArchive(archivePath, platformCacheDir, target.ext);

  const javaHomeAbs = findJavaHome(platformCacheDir, target.os);
  if (!javaHomeAbs) {
    fs.rmSync(platformCacheDir, { recursive: true, force: true });
    throw new Error(
      `해제물에서 java_home(bin/${javaExecutableName(target.os)})을 찾지 못했습니다. 캐시 폴더를 삭제했습니다.`
    );
  }

  const javaHomeRel = path.relative(platformCacheDir, javaHomeAbs);
  const resolved = {
    releaseName: meta.releaseName || effectiveRelease,
    channel: effectiveChannel,
    semver: meta.semver,
    javaHome: javaHomeRel,
    sha256: meta.checksum,
  };
  fs.writeFileSync(resolvedJsonPath, `${JSON.stringify(resolved, null, 2)}\n`);

  // The archive is no longer needed once extracted.
  fs.rmSync(archivePath, { force: true });

  success(`JRE ready: ${javaHomeAbs} (semver ${meta.semver}).`);
  return { javaHome: javaHomeAbs, semver: meta.semver, source: 'download' };
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const opts = { force: false, check: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--os') {
      opts.os = argv[++i];
    } else if (arg === '--arch') {
      opts.arch = argv[++i];
    } else if (arg === '--cache-dir') {
      opts.cacheDir = argv[++i];
    } else if (arg === '--release') {
      opts.release = argv[++i];
    } else if (arg === '--force') {
      opts.force = true;
    } else if (arg === '--check') {
      opts.check = true;
    } else {
      warn(`알 수 없는 인자 무시: ${arg}`);
    }
  }
  return opts;
}

async function mainCli() {
  const opts = parseArgs(process.argv.slice(2));
  const platform = opts.os ? normalizePlatform(opts.os) : process.platform;
  const arch = opts.arch ? normalizeArch(opts.arch) : process.arch;
  const cacheDir = opts.cacheDir ? path.resolve(opts.cacheDir) : DEFAULT_CACHE_DIR;
  const releaseName = opts.release || JRE_RELEASE_NAME;
  const channel = process.env.SASOO_JRE_CHANNEL === 'latest' ? 'latest' : 'release';

  if (opts.check) {
    const target = resolveTarget(normalizePlatform(platform), normalizeArch(arch));
    const platformCacheDir = path.join(cacheDir, `${target.os}-${target.arch}`);
    const resolvedJsonPath = path.join(platformCacheDir, 'resolved.json');
    const cached = readCacheIfValid(platformCacheDir, resolvedJsonPath, releaseName, channel, target);
    if (cached) {
      success(`[check] 캐시 유효: ${cached.javaHome} (semver ${cached.semver})`);
    } else {
      info(`[check] 캐시 없음/무효: ${platformCacheDir} (release=${releaseName}, channel=${channel})`);
    }
    return;
  }

  const result = await ensureJavaRuntime({ platform, arch, cacheDir, releaseName, channel, force: opts.force });
  success(`javaHome=${result.javaHome}`);
  success(`semver=${result.semver} source=${result.source}`);
}

if (require.main === module) {
  mainCli().catch((e) => {
    error(e.message);
    process.exit(1);
  });
}

module.exports = {
  JRE_RELEASE_NAME,
  ensureJavaRuntime,
  resolveTarget,
  fetchReleaseMeta,
  downloadWithRetry,
  verifySha256,
  extractArchive,
  findJavaHome,
  normalizePlatform,
  normalizeArch,
};
