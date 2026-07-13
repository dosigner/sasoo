// electron-builder afterSign hook — notarizes the macOS .app when Apple
// credentials are present. Without them it is a no-op so unsigned builds are
// byte-for-byte unchanged from the pre-signing pipeline.
//
// Exported both as module.exports and module.exports.default so it works
// whether the caller requires the function directly or reads the `.default`
// named export (electron-builder resolves the hook via `.default`).
async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;

  if (electronPlatformName !== 'darwin') {
    return;
  }

  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_APP_SPECIFIC_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;

  if (!appleId || !appleIdPassword || !teamId) {
    console.log('[notarize] Apple 자격증명 미설정 → 공증 건너뜀 (미서명/미공증 빌드)');
    return;
  }

  const productFilename = context.packager.appInfo.productFilename;
  const appPath = `${appOutDir}/${productFilename}.app`;

  console.log(`[notarize] notarytool로 공증 시작: ${appPath}`);

  const { notarize } = require('@electron/notarize');
  await notarize({
    tool: 'notarytool',
    appPath,
    appleId,
    appleIdPassword,
    teamId,
  });

  console.log(`[notarize] 공증 완료: ${productFilename}.app`);
}

module.exports = notarizing;
module.exports.default = notarizing;
