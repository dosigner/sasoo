const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

function log(message) {
  console.log(`[after-sign] ${message}`);
}

function run(command, args) {
  return execFileSync(command, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function capture(command, args) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `${command} failed`);
  }

  return `${result.stdout || ''}${result.stderr || ''}`;
}

module.exports = async function afterSign(context) {
  if (context.electronPlatformName !== 'darwin') {
    return;
  }

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);

  log(`Verifying signed app bundle at ${appPath}`);
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath]);

  if (process.env.CI_RELEASE === 'true' || process.env.REQUIRE_SIGNED_MAC_RELEASE === 'true') {
    const details = capture('codesign', ['-dv', '--verbose=4', appPath]);

    if (details.includes('Signature=adhoc')) {
      throw new Error('Release builds must not use ad-hoc signing.');
    }

    if (details.includes('TeamIdentifier=not set')) {
      throw new Error('Release builds must use a real Apple Developer Team identity.');
    }
  }
};
