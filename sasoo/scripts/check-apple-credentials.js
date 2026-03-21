const fs = require('fs');

const args = new Set(process.argv.slice(2));
const requireRelease = args.has('--require-release');

const requiredEnv = [
  'APPLE_API_KEY',
  'APPLE_API_KEY_ID',
  'APPLE_API_ISSUER',
  'CSC_LINK',
  'CSC_KEY_PASSWORD',
];

function log(message) {
  console.log(`[check-apple-credentials] ${message}`);
}

function fail(message) {
  console.error(`[check-apple-credentials] ${message}`);
  process.exit(1);
}

function hasValue(name) {
  return typeof process.env[name] === 'string' && process.env[name].trim().length > 0;
}

const missing = requiredEnv.filter((name) => !hasValue(name));

if (requireRelease && missing.length > 0) {
  fail(`Missing required Apple release environment variables: ${missing.join(', ')}`);
}

if (hasValue('APPLE_API_KEY')) {
  const appleApiKeyPath = process.env.APPLE_API_KEY.trim();
  const looksLikePath =
    appleApiKeyPath.startsWith('/') ||
    appleApiKeyPath.startsWith('./') ||
    appleApiKeyPath.startsWith('../');

  if (looksLikePath && !fs.existsSync(appleApiKeyPath)) {
    fail(`APPLE_API_KEY points to a file that does not exist: ${appleApiKeyPath}`);
  }
}

if (requireRelease) {
  log('Apple signing and notarization credentials are present.');
} else if (missing.length > 0) {
  log(`Apple release credentials are not fully configured yet: ${missing.join(', ')}`);
} else {
  log('Apple release credentials are configured.');
}
